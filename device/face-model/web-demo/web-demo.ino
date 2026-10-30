// web-demo: face-model 시연용. XIAO ESP32S3가 Wi-Fi에 붙어 웹서버를 띄우고,
// 브라우저에서 카메라 화면 위에 얼굴 박스·점수를 실시간으로 보여 준다. MQTT·broker는 쓰지 않는다.
// 카메라 → 모델 실행은 ../face-model.ino와 같다. 브라우저에 보이는 사진과 박스는 같은 프레임이다.
// 준비: secrets.example.h를 secrets.h로 복사해 Wi-Fi를 채운다. Tools → PSRAM → OPI PSRAM.

#include <WiFi.h>
#include <ESPmDNS.h>
#include "esp_http_server.h"
#include <Face_detection_-_FOMO_-_bigger_dataset_inferencing.h>
#include "edge-impulse-sdk/dsp/image/image.hpp"
#include "esp_camera.h"
#include "secrets.h"  // WIFI_SSID, WIFI_PASSWORD (커밋하지 않음)

// ================= 설정 =================
const float FACE_THRESHOLD = 0.5f;          // 모델 자체 threshold(0.5) 이상만 의미가 있다
const char* MDNS_NAME      = "face-model";  // http://face-model.local/
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

#define RAW_COLS 320
#define RAW_ROWS 240
#define RAW_BPP  3
#define JPEG_MAX (64 * 1024)  // QVGA JPEG 한 장은 보통 10~20KB

#if !defined(EI_CLASSIFIER_SENSOR) || EI_CLASSIFIER_SENSOR != EI_CLASSIFIER_SENSOR_CAMERA
#error "카메라용 모델이 아니다"
#endif

struct FaceResult {
  bool face;
  float score;
  int count;
  uint32_t inferMs;
};

// Edge Impulse 라이브러리의 ei_calloc(weak)을 바꿔 끼운다. ESP32-S3 가속(ESP-NN)은 임시 버퍼가 16바이트 정렬이라고 가정하는데,
// 라이브러리는 ESP-IDF 5(esp32 코어 3.x)에서 정렬 없이 할당해 버퍼 밖을 덮어쓰고 CORRUPT HEAP으로 재부팅된다.
// 해제는 라이브러리의 ei_free(= free)가 그대로 한다. (Arduino가 첫 함수 앞에 선언을 끼우므로 struct 뒤에 둔다)
void* ei_calloc(size_t nitems, size_t size) {
  return heap_caps_aligned_calloc(16, nitems, size, MALLOC_CAP_DEFAULT);
}

static uint8_t* snapshotBuf = nullptr;  // RGB888 원본, 리사이즈 후 앞부분이 모델 입력

// 브라우저로 보낼 마지막 프레임과 그 결과. 웹서버 태스크와 loop()가 같이 쓰므로 lock으로 묶는다
static SemaphoreHandle_t lock;
static uint8_t* jpegBuf = nullptr;
static size_t jpegLen = 0;
static char resultJson[640] = "";

static httpd_handle_t server = nullptr;

// ---------- 카메라 · 모델 ----------
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
  c.fb_count     = 2;
  c.fb_location  = CAMERA_FB_IN_PSRAM;
  c.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("[cam] 초기화 실패 0x%x\n", err);
    return false;
  }
  sensor_t* s = esp_camera_sensor_get();
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);  // OV3660은 위아래가 뒤집혀 나온다
    s->set_brightness(s, 1);
    s->set_saturation(s, 0);
  }
  return true;
}

static int getSignalData(size_t offset, size_t length, float* out) {
  size_t px = offset * 3;
  for (size_t i = 0; i < length; i++, px += 3) {
    // fmt2rgb888은 BGR 순서로 쓴다 (esp32-camera#379)
    out[i] = (snapshotBuf[px + 2] << 16) + (snapshotBuf[px + 1] << 8) + snapshotBuf[px];
  }
  return 0;
}

// 한 장 찍어 모델을 돌리고, 그 JPEG과 결과(JSON)를 브라우저용으로 저장한다
bool runOnce(FaceResult& out) {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[cam] 촬영 실패");
    return false;
  }
  bool ok = fmt2rgb888(fb->buf, fb->len, PIXFORMAT_JPEG, snapshotBuf);
  if (!ok) {
    esp_camera_fb_return(fb);
    Serial.println("[cam] JPEG 변환 실패");
    return false;
  }
  // 가운데를 정사각형으로 잘라 모델 입력 크기로 줄인다
  ei::image::processing::crop_and_interpolate_rgb888(
      snapshotBuf, RAW_COLS, RAW_ROWS,
      snapshotBuf, EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT);

  ei::signal_t signal;
  signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
  signal.get_data = &getSignalData;

  ei_impulse_result_t result = {};
  EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
  if (err != EI_IMPULSE_OK) {
    esp_camera_fb_return(fb);
    Serial.printf("[model] 실행 실패 (%d)\n", err);
    return false;
  }

  // 박스 좌표는 모델 입력(96×96) 기준. 브라우저가 화면 크기에 맞춰 늘린다
  char boxes[400] = "";
  size_t bl = 0;
  out = {false, 0.0f, 0, (uint32_t)(result.timing.dsp + result.timing.classification)};
  for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
    const ei_impulse_result_bounding_box_t& bb = result.bounding_boxes[i];
    if (bb.value < FACE_THRESHOLD) continue;
    out.count++;
    if (bb.value > out.score) out.score = bb.value;
    bl += snprintf(boxes + bl, sizeof(boxes) - bl, "%s[%u,%u,%u,%u,%.2f]",
                   bl ? "," : "", bb.x, bb.y, bb.width, bb.height, bb.value);
    if (bl >= sizeof(boxes)) break;
  }
  out.face = out.count > 0;

  xSemaphoreTake(lock, portMAX_DELAY);
  if (fb->len <= JPEG_MAX) {
    memcpy(jpegBuf, fb->buf, fb->len);
    jpegLen = fb->len;
    snprintf(resultJson, sizeof(resultJson),
             "{\"face\":%s,\"score\":%.2f,\"count\":%d,\"infer_ms\":%u,\"in\":%d,\"w\":%d,\"h\":%d,\"boxes\":[%s]}",
             out.face ? "true" : "false", out.score, out.count, out.inferMs,
             EI_CLASSIFIER_INPUT_WIDTH, RAW_COLS, RAW_ROWS, boxes);
  }
  xSemaphoreGive(lock);

  esp_camera_fb_return(fb);
  return true;
}

// ---------- 웹 ----------
static const char INDEX_HTML[] = R"HTML(<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Face Model Demo</title>
<style>
body{margin:0;padding:16px;background:#111;color:#eee;font-family:system-ui,sans-serif;text-align:center}
#state{font-size:32px;font-weight:700;margin:8px 0 12px}.on{color:#4ade80}.off{color:#f87171}
#view{position:relative;display:inline-block;width:640px;max-width:100%}
#view img{display:block;width:100%}#view canvas{position:absolute;left:0;top:0;width:100%;height:100%}
#meta{margin-top:10px;color:#aaa;font-size:14px;font-variant-numeric:tabular-nums}
</style></head><body>
<div id="state">연결 중…</div>
<div id="view"><img id="img" alt=""><canvas id="cv" width="320" height="240"></canvas></div>
<div id="meta"></div>
<script>
const img=document.getElementById('img'),cv=document.getElementById('cv'),ctx=cv.getContext('2d');
const state=document.getElementById('state'),meta=document.getElementById('meta');
let n=0,t0=performance.now(),fps=0;
function draw(r){
  cv.width=r.w;cv.height=r.h;ctx.clearRect(0,0,r.w,r.h);
  // 모델은 가운데 정사각형(h×h)을 in×in으로 줄여 본다
  const k=r.h/r.in,ox=(r.w-r.h)/2;
  ctx.strokeStyle='rgba(255,255,255,.35)';ctx.setLineDash([4,4]);ctx.strokeRect(ox,0,r.h,r.h);ctx.setLineDash([]);
  ctx.strokeStyle=ctx.fillStyle='#4ade80';ctx.lineWidth=2;ctx.font='bold 12px system-ui';
  for(const [x,y,w,h,s] of r.boxes){
    const bx=ox+x*k,by=y*k;ctx.strokeRect(bx,by,w*k,h*k);ctx.fillText(s.toFixed(2),bx,Math.max(12,by-3));
  }
  state.textContent=r.face?'얼굴 있음':'얼굴 없음';state.className=r.face?'on':'off';
  n++;const dt=(performance.now()-t0)/1000;if(dt>=2){fps=n/dt;n=0;t0=performance.now();}
  meta.textContent=`score ${r.score.toFixed(2)} · count ${r.count} · infer ${r.infer_ms} ms · ${fps.toFixed(1)} fps`;
}
async function tick(){
  try{
    const res=await fetch('/frame',{cache:'no-store'});
    if(res.ok){
      const r=JSON.parse(res.headers.get('X-Result'));
      const url=URL.createObjectURL(await res.blob());
      img.onload=()=>URL.revokeObjectURL(url);img.src=url;draw(r);
    }else await new Promise(ok=>setTimeout(ok,200));
  }catch(e){
    state.textContent='연결 끊김';state.className='off';await new Promise(ok=>setTimeout(ok,1000));
  }
  setTimeout(tick,0);
}
tick();
</script></body></html>)HTML";

static esp_err_t indexHandler(httpd_req_t* req) {
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

// 마지막 프레임 JPEG. 그 프레임의 감지 결과는 X-Result 헤더에 JSON으로 싣는다
static esp_err_t frameHandler(httpd_req_t* req) {
  xSemaphoreTake(lock, portMAX_DELAY);
  if (jpegLen == 0) {
    xSemaphoreGive(lock);
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_send(req, nullptr, 0);
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  httpd_resp_set_hdr(req, "X-Result", resultJson);
  esp_err_t err = httpd_resp_send(req, (const char*)jpegBuf, jpegLen);
  xSemaphoreGive(lock);
  return err;
}

bool startServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  if (httpd_start(&server, &config) != ESP_OK) return false;
  httpd_uri_t index = {.uri = "/", .method = HTTP_GET, .handler = indexHandler, .user_ctx = nullptr};
  httpd_uri_t frame = {.uri = "/frame", .method = HTTP_GET, .handler = frameHandler, .user_ctx = nullptr};
  httpd_register_uri_handler(server, &index);
  httpd_register_uri_handler(server, &frame);
  return true;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // 절전 모드면 프레임 전송이 끊긴다
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("[wifi] %s 연결 중", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[wifi] %s\n", WiFi.localIP().toString().c_str());
}

// ---------- 메인 ----------
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
  lock = xSemaphoreCreateMutex();
  snapshotBuf = (uint8_t*)ps_malloc(RAW_COLS * RAW_ROWS * RAW_BPP);
  jpegBuf = (uint8_t*)ps_malloc(JPEG_MAX);
  if (!snapshotBuf || !jpegBuf || !initCamera()) {
    Serial.println("[boot] 초기화 실패, 재부팅");
    delay(1000);
    ESP.restart();
  }

  connectWiFi();
  if (MDNS.begin(MDNS_NAME)) MDNS.addService("http", "tcp", 80);
  if (!startServer()) {
    Serial.println("[web] 서버 시작 실패, 재부팅");
    delay(1000);
    ESP.restart();
  }
  Serial.printf("[web] 브라우저에서 http://%s/ 또는 http://%s.local/\n",
                WiFi.localIP().toString().c_str(), MDNS_NAME);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  FaceResult r;
  if (!runOnce(r)) {
    delay(100);
    return;
  }
  digitalWrite(LED_PIN, r.face ? LOW : HIGH);
  Serial.printf("face=%s score=%.2f count=%d infer_ms=%u\n", r.face ? "true" : "false", r.score, r.count, r.inferMs);
}
