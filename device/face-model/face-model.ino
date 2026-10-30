// face-model: XIAO ESP32S3에서 Edge Impulse 얼굴 감지 모델(FOMO)만 단독으로 돌려 보는 스케치.
// 카메라 한 장 → 96×96 RGB로 줄임 → 모델 실행 → 결과를 시리얼로 출력. Wi-Fi·MQTT는 없다 (face-detector 담당).
// runFaceModel()이 돌려주는 값은 docs/contracts/README.md의 face 메시지 필드(face, score, count, infer_ms)와 같다.
// 라이브러리: 이 폴더의 Edge Impulse .zip을 Sketch → Include Library → Add .ZIP Library로 설치.

#include <Face_detection_-_FOMO_-_bigger_dataset_inferencing.h>
#include "edge-impulse-sdk/dsp/image/image.hpp"
#include "esp_camera.h"

// ================= 설정 =================
// 얼굴로 칠 최소 점수. 모델 자체 threshold(0.5) 아래 박스는 모델이 이미 버리므로 0.5 이상만 의미가 있다.
const float FACE_THRESHOLD = 0.5f;
const bool  PRINT_BOXES    = true;   // 박스 좌표까지 출력
// ========================================

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
#define LED_PIN        21  // 사용자 LED (LOW = 켜짐). 얼굴이 보이면 켠다

// 카메라는 QVGA JPEG로 찍고 RGB888로 풀어 모델 입력 크기로 줄인다
#define RAW_COLS 320
#define RAW_ROWS 240
#define RAW_BPP  3

#if !defined(EI_CLASSIFIER_SENSOR) || EI_CLASSIFIER_SENSOR != EI_CLASSIFIER_SENSOR_CAMERA
#error "카메라용 모델이 아니다"
#endif

struct FaceResult {
  bool face;         // FACE_THRESHOLD를 넘은 얼굴이 하나라도 있으면 true
  float score;       // 가장 높은 얼굴 점수 (없으면 0)
  int count;         // FACE_THRESHOLD를 넘은 얼굴 수
  uint32_t inferMs;  // 전처리(DSP) + 모델 실행 시간
};

// Edge Impulse 라이브러리의 ei_calloc(weak)을 바꿔 끼운다. ESP32-S3 가속(ESP-NN)은 임시 버퍼가 16바이트 정렬이라고 가정하는데,
// 라이브러리는 ESP-IDF 5(esp32 코어 3.x)에서 정렬 없이 할당해 버퍼 밖을 덮어쓰고 CORRUPT HEAP으로 재부팅된다.
// 해제는 라이브러리의 ei_free(= free)가 그대로 한다. (Arduino가 첫 함수 앞에 선언을 끼우므로 struct 뒤에 둔다)
void* ei_calloc(size_t nitems, size_t size) {
  return heap_caps_aligned_calloc(16, nitems, size, MALLOC_CAP_DEFAULT);
}

static uint8_t* snapshotBuf = nullptr;  // RAW_COLS×RAW_ROWS×3, PSRAM. 리사이즈 후 앞부분이 96×96 입력이 된다

bool initCamera() {
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
    Serial.printf("[cam] 초기화 실패 0x%x\n", err);
    return false;
  }
  sensor_t* s = esp_camera_sensor_get();
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);       // OV3660은 위아래가 뒤집혀 나온다
    s->set_brightness(s, 1);
    s->set_saturation(s, 0);
  }
  return true;
}

// 카메라 한 장 → snapshotBuf 앞부분에 EI_CLASSIFIER_INPUT_WIDTH×HEIGHT RGB888
bool captureFrame() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[cam] 촬영 실패");
    return false;
  }
  bool ok = fmt2rgb888(fb->buf, fb->len, PIXFORMAT_JPEG, snapshotBuf);
  esp_camera_fb_return(fb);
  if (!ok) {
    Serial.println("[cam] JPEG 변환 실패");
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

// 한 장 찍어 모델을 돌린다. 실패하면 false
bool runFaceModel(FaceResult& out) {
  if (!captureFrame()) return false;

  ei::signal_t signal;
  signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
  signal.get_data = &getSignalData;

  ei_impulse_result_t result = {};
  EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
  if (err != EI_IMPULSE_OK) {
    Serial.printf("[model] 실행 실패 (%d)\n", err);
    return false;
  }

  out = {false, 0.0f, 0, (uint32_t)(result.timing.dsp + result.timing.classification)};
  for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
    const ei_impulse_result_bounding_box_t& bb = result.bounding_boxes[i];
    if (bb.value < FACE_THRESHOLD) continue;
    out.count++;
    if (bb.value > out.score) out.score = bb.value;
    if (PRINT_BOXES) {
      Serial.printf("  %s %.2f [x=%u y=%u w=%u h=%u]\n", bb.label, bb.value, bb.x, bb.y, bb.width, bb.height);
    }
  }
  out.face = out.count > 0;
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  Serial.printf("[boot] model=%s 입력 %dx%d, threshold=%.2f\n",
                EI_CLASSIFIER_PROJECT_NAME, EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT, FACE_THRESHOLD);

  if (!psramFound()) {
    Serial.println("[boot] PSRAM 없음. Tools → PSRAM → OPI PSRAM으로 바꾼다");
    while (true) delay(1000);
  }
  snapshotBuf = (uint8_t*)ps_malloc(RAW_COLS * RAW_ROWS * RAW_BPP);
  if (!snapshotBuf || !initCamera()) {
    Serial.println("[boot] 초기화 실패, 재부팅");
    delay(1000);
    ESP.restart();
  }
  Serial.println("[boot] 준비됨");
}

void loop() {
  FaceResult r;
  if (!runFaceModel(r)) {
    delay(100);
    return;
  }
  digitalWrite(LED_PIN, r.face ? LOW : HIGH);
  // face 메시지와 같은 필드 순서
  Serial.printf("face=%s score=%.2f count=%d infer_ms=%u\n", r.face ? "true" : "false", r.score, r.count, r.inferMs);
}
