// 카메라 + face-model 실행. 처리 흐름은 device/face-model/face-model.ino(김대희)와 같다:
// QVGA(320×240) JPEG → RGB888로 풀기 → 가운데 정사각형을 96×96으로 줄이기 → 모델 실행.
#include <Face_detection_-_FOMO_-_bigger_dataset_inferencing.h>
#include "edge-impulse-sdk/dsp/image/image.hpp"
#include "esp_camera.h"
#include <freertos/semphr.h>
#include <utility>
#include "face_runner.h"
#include "log.h"

#if !defined(EI_CLASSIFIER_SENSOR) || EI_CLASSIFIER_SENSOR != EI_CLASSIFIER_SENSOR_CAMERA
#error "카메라용 모델이 아니다"
#endif

// 얼굴로 칠 최소 점수. 모델 자체 threshold(0.5) 아래 박스는 모델이 이미 버리므로 0.5 이상만 의미가 있다
static const float FACE_THRESHOLD = 0.5f;
static const uint32_t ERROR_LOG_INTERVAL_MS = 5000;  // 촬영 실패가 이어져도 ERROR는 이 간격으로만

// XIAO ESP32S3 Sense 카메라 핀 (camera_pins.h의 CAMERA_MODEL_XIAO_ESP32S3)
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  10
#define SIOD_GPIO_NUM  40
#define SIOC_GPIO_NUM  39
#define Y9_GPIO_NUM    48
#define Y8_GPIO_NUM    11
#define Y7_GPIO_NUM    12
#define Y6_GPIO_NUM    14
#define Y5_GPIO_NUM    16
#define Y4_GPIO_NUM    18
#define Y3_GPIO_NUM    17
#define Y2_GPIO_NUM    15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM  47
#define PCLK_GPIO_NUM  13

#define RAW_COLS 320
#define RAW_ROWS 240
#define RAW_BPP  3

// Edge Impulse의 ei_calloc(weak)을 바꿔 끼운다. ESP32-S3 가속(ESP-NN)은 임시 버퍼가 16바이트 정렬이라고 가정하는데,
// 라이브러리는 ESP-IDF 5(esp32 코어 3.x)에서 정렬 없이 할당해 CORRUPT HEAP으로 재부팅된다 (device/face-model/WORKLOG.md 6장).
void* ei_calloc(size_t nitems, size_t size) {
  return heap_caps_aligned_calloc(16, nitems, size, MALLOC_CAP_DEFAULT);
}

static uint8_t* snapshotBuf = nullptr;  // RAW_COLS×RAW_ROWS×3, PSRAM. 줄인 뒤 앞부분이 96×96 입력이 된다
static uint32_t lastErrorMs = 0;

// 미리보기: loop가 모델을 돌린 장을 pendingJpeg에 찍어 두고, 추론이 끝나면 박스와 함께 previewJpeg와 바꾼다.
// 웹 서버 태스크도 카메라와 previewJpeg를 쓰므로 cameraLock 안에서만 만진다 (pendingJpeg는 loop만 쓴다)
#define PREVIEW_JPEG_CAP (64 * 1024)   // QVGA JPEG는 보통 10~20KB
#define PREVIEW_IDLE_MS 1000           // 이만큼 추론이 없으면 감지가 꺼진 것으로 보고 미리보기가 직접 찍는다
static SemaphoreHandle_t cameraLock = nullptr;
static uint8_t* pendingJpeg = nullptr;
static uint8_t* previewJpeg = nullptr;
static size_t pendingLen = 0;
static PreviewFrame preview = {};
static uint32_t lastInferMs = 0;

static void logErrorThrottled(const char* module, const char* msg, int code) {
  if (lastErrorMs && millis() - lastErrorMs < ERROR_LOG_INTERVAL_MS) return;
  lastErrorMs = millis();
  LOGE(module, "%s code=%d", msg, code);
}

const char* faceModelVersion() {
  static char version[32];
  snprintf(version, sizeof version, "ei-%d-v%d", EI_CLASSIFIER_PROJECT_ID, EI_CLASSIFIER_PROJECT_DEPLOY_VERSION);
  return version;
}

static bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer   = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk     = XCLK_GPIO_NUM;
  c.pin_pclk     = PCLK_GPIO_NUM;
  c.pin_vsync    = VSYNC_GPIO_NUM;
  c.pin_href     = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn     = PWDN_GPIO_NUM;
  c.pin_reset    = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size   = FRAMESIZE_QVGA;
  c.jpeg_quality = 12;
  c.fb_count     = 1;
  c.fb_location  = CAMERA_FB_IN_PSRAM;
  c.grab_mode    = CAMERA_GRAB_LATEST;  // 추론하는 동안 쌓인 오래된 프레임 대신 최신 프레임

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    LOGC("camera", "카메라 초기화 실패 err=0x%x", (unsigned)err);
    return false;
  }
  sensor_t* s = esp_camera_sensor_get();
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);  // OV3660은 위아래가 뒤집혀 나온다
    s->set_brightness(s, 1);
    s->set_saturation(s, 0);
  }
  LOGI("camera", "카메라 초기화 sensor_pid=0x%x frame_size=%dx%d format=jpeg",
       (unsigned)s->id.PID, RAW_COLS, RAW_ROWS);
  return true;
}

bool faceModelBegin() {
  if (!psramFound()) {
    LOGC("camera", "PSRAM 없음. Tools → PSRAM → OPI PSRAM으로 업로드한다");
    return false;
  }
  snapshotBuf = (uint8_t*)ps_malloc(RAW_COLS * RAW_ROWS * RAW_BPP);
  pendingJpeg = (uint8_t*)ps_malloc(PREVIEW_JPEG_CAP);
  previewJpeg = (uint8_t*)ps_malloc(PREVIEW_JPEG_CAP);
  cameraLock = xSemaphoreCreateMutex();
  if (!snapshotBuf || !pendingJpeg || !previewJpeg || !cameraLock) {
    LOGC("camera", "프레임 버퍼 할당 실패 need_kb=%d", (RAW_COLS * RAW_ROWS * RAW_BPP + 2 * PREVIEW_JPEG_CAP) / 1024);
    return false;
  }
  if (!initCamera()) return false;
  LOGI("infer", "모델 준비 model=%s input=%dx%d threshold=%.2f",
       faceModelVersion(), EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT, FACE_THRESHOLD);
  return true;
}

// 카메라 한 장 → snapshotBuf 앞부분에 EI_CLASSIFIER_INPUT_WIDTH×HEIGHT RGB888
static bool captureFrame() {
  xSemaphoreTake(cameraLock, portMAX_DELAY);
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    xSemaphoreGive(cameraLock);
    logErrorThrottled("camera", "프레임 촬영 실패", 0);
    return false;
  }
  pendingLen = fb->len <= PREVIEW_JPEG_CAP ? fb->len : 0;  // 너무 크면 미리보기만 건너뛴다
  memcpy(pendingJpeg, fb->buf, pendingLen);
  bool ok = fmt2rgb888(fb->buf, fb->len, PIXFORMAT_JPEG, snapshotBuf);
  esp_camera_fb_return(fb);
  xSemaphoreGive(cameraLock);
  if (!ok) {
    logErrorThrottled("camera", "JPEG 변환 실패", 0);
    return false;
  }
  // 가운데를 정사각형으로 잘라 모델 입력 크기로 줄인다 (Edge Impulse 학습 때와 같은 방식)
  ei::image::processing::crop_and_interpolate_rgb888(
      snapshotBuf, RAW_COLS, RAW_ROWS,
      snapshotBuf, EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT);
  return true;
}

// Edge Impulse가 입력을 읽어 가는 콜백. 픽셀 하나를 0xRRGGBB 정수(float)로 넘긴다
static int getSignalData(size_t offset, size_t length, float* out) {
  size_t px = offset * 3;
  for (size_t i = 0; i < length; i++, px += 3) {
    // fmt2rgb888은 BGR 순서로 쓴다 (esp32-camera#379)
    out[i] = (snapshotBuf[px + 2] << 16) + (snapshotBuf[px + 1] << 8) + snapshotBuf[px];
  }
  return 0;
}

bool runFaceModel(FaceResult& out) {
  uint32_t t0 = millis();
  if (!captureFrame()) return false;
  uint32_t captureMs = millis() - t0;

  ei::signal_t signal;
  signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
  signal.get_data = &getSignalData;

  ei_impulse_result_t result = {};
  EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
  if (err != EI_IMPULSE_OK) {
    logErrorThrottled("infer", "모델 실행 실패", (int)err);
    return false;
  }

  out = {false, 0.0f, 0, (uint32_t)(result.timing.dsp + result.timing.classification), captureMs};
  int cropX, cropY, cropSide;
  faceModelCropRect(cropX, cropY, cropSide);
  float scale = (float)cropSide / EI_CLASSIFIER_INPUT_WIDTH;
  PreviewFrame frame = {pendingLen, true, 0};
  for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
    const ei_impulse_result_bounding_box_t& bb = result.bounding_boxes[i];
    if (bb.value < FACE_THRESHOLD) continue;
    out.count++;
    if (bb.value > out.score) out.score = bb.value;
    if (frame.boxCount < PREVIEW_MAX_BOXES) {
      // 박스는 96×96 입력 좌표. 가운데 정사각형을 줄인 것이므로 거꾸로 늘려 원본 픽셀로 바꾼다
      frame.boxes[frame.boxCount++] = {(int16_t)(cropX + bb.x * scale), (int16_t)(cropY + bb.y * scale),
                                       (int16_t)(bb.width * scale), (int16_t)(bb.height * scale), bb.value};
    }
  }
  out.face = out.count > 0;

  if (pendingLen) {
    xSemaphoreTake(cameraLock, portMAX_DELAY);
    std::swap(pendingJpeg, previewJpeg);
    preview = frame;
    lastInferMs = millis();
    xSemaphoreGive(cameraLock);
  }
  return true;
}

// ───────── 미리보기 ─────────

void faceModelCropRect(int& x, int& y, int& side) {
  // crop_and_interpolate_rgb888은 입력 비율(1:1)에 맞춰 가운데를 자른다
  side = min(RAW_COLS, RAW_ROWS);
  x = (RAW_COLS - side) / 2;
  y = (RAW_ROWS - side) / 2;
}

bool faceModelPreview(uint8_t* dst, size_t cap, PreviewFrame& out) {
  if (!cameraLock) return false;
  xSemaphoreTake(cameraLock, portMAX_DELAY);
  if (!lastInferMs || millis() - lastInferMs > PREVIEW_IDLE_MS) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) {
      size_t len = fb->len <= PREVIEW_JPEG_CAP ? fb->len : 0;
      memcpy(previewJpeg, fb->buf, len);
      preview = {len, false, 0};
      esp_camera_fb_return(fb);
    }
  }
  bool ok = preview.jpegLen && preview.jpegLen <= cap;
  if (ok) {
    memcpy(dst, previewJpeg, preview.jpegLen);
    out = preview;
  }
  xSemaphoreGive(cameraLock);
  return ok;
}
