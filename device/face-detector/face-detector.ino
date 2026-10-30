// face-detector: ESP32에서 카메라 프레임마다 face-model을 실행해 얼굴 감지 결과를 보낸다. Wi-Fi·MQTT 연결, status 발행, control(start/stop) 받기.
// 카메라 촬영과 face-model 실행은 아직 없다. loop()의 TODO 자리에서 publishFace()를 부른다.
// 메시지 형식은 docs/contracts/README.md. 시리얼 로그 형식은 log.h.

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "secrets.h"  // .env를 채운 뒤 python gen_secrets.py로 만든다 (커밋하지 않음)
#include "log.h"

#define FW_VERSION "0.2.0"
#define MODEL_VERSION "none"     // face-model을 붙이면 모델 버전 이름으로 바꾼다
#define WEAK_RSSI_DBM -75        // 이보다 약하면 WARNING
#define WIFI_WAIT_WARN_MS 10000  // Wi-Fi 연결을 이만큼 기다릴 때마다 WARNING

WiFiClient net;
PubSubClient mqtt(net);

String topicControl = String("zt/") + DEVICE_ID + "/control";
String topicFace    = String("zt/") + DEVICE_ID + "/face";
String topicStatus  = String("zt/") + DEVICE_ID + "/status";

bool running = false;
uint32_t seq = 0;

void publishStatus() {
  JsonDocument doc;
  doc["state"] = running ? "running" : "idle";
  doc["fw"] = FW_VERSION;
  char buf[96];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(topicStatus.c_str(), (const uint8_t*)buf, n, true);  // retain
}

// 추론 한 번의 결과를 보낸다. score: 가장 높은 얼굴 점수(없으면 0), count: threshold를 넘은 얼굴 수
void publishFace(bool face, float score, int count, uint32_t inferMs) {
  JsonDocument doc;
  doc["seq"] = seq++;
  doc["face"] = face;
  doc["score"] = score;
  doc["count"] = count;
  doc["infer_ms"] = inferMs;
  char buf[128];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(topicFace.c_str(), (const uint8_t*)buf, n, false);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) {
    LOGE("mqtt", "잘못된 메시지 topic=%s reason=json len=%u", topic, len);
    return;
  }
  const char* cmd = doc["cmd"] | "";
  if (strcmp(cmd, "start") == 0) running = true;
  else if (strcmp(cmd, "stop") == 0) running = false;
  else {
    LOGE("mqtt", "잘못된 메시지 topic=%s reason=unknown_cmd cmd=%s", topic, cmd);
    return;
  }
  LOGI("mqtt", "control 받음 cmd=%s state=%s", cmd, running ? "running" : "idle");
  publishStatus();
}

void connectWiFi() {
  static uint32_t reconnects = 0;
  static bool connectedBefore = false;
  if (connectedBefore) LOGW("wifi", "끊김, 다시 연결 count=%u", (unsigned)++reconnects);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  LOGI("wifi", "연결 중 ssid=%s", WIFI_SSID);
  unsigned long t0 = millis();
  unsigned long nextWarn = t0 + WIFI_WAIT_WARN_MS;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    if (millis() >= nextWarn) {
      LOGW("wifi", "아직 연결 안 됨 ssid=%s status=%d waited_ms=%lu", WIFI_SSID, (int)WiFi.status(), millis() - t0);
      nextWarn += WIFI_WAIT_WARN_MS;
    }
  }
  connectedBefore = true;

  int rssi = WiFi.RSSI();
  LOGI("wifi", "연결됨 ssid=%s ip=%s rssi_dbm=%d connect_ms=%lu",
       WIFI_SSID, WiFi.localIP().toString().c_str(), rssi, millis() - t0);
  if (rssi < WEAK_RSSI_DBM) LOGW("wifi", "신호 약함 rssi_dbm=%d", rssi);
}

void connectMqtt() {
  static uint32_t reconnects = 0;
  static bool connectedBefore = false;
  if (connectedBefore) LOGW("mqtt", "끊김, 다시 연결 count=%u", (unsigned)++reconnects);

  LOGI("mqtt", "연결 중 broker=%s:%d", BROKER_HOST, BROKER_PORT);
  uint32_t failures = 0;
  while (!mqtt.connected()) {
    // LWT: 보드가 끊기면 broker가 대신 offline을 retain으로 남긴다
    if (mqtt.connect(DEVICE_ID, topicStatus.c_str(), 1, true, "{\"state\":\"offline\"}")) {
      mqtt.subscribe(topicControl.c_str(), 1);
      publishStatus();
      connectedBefore = true;
      LOGI("mqtt", "연결됨 broker=%s:%d client_id=%s", BROKER_HOST, BROKER_PORT, DEVICE_ID);
    } else {
      LOGW("mqtt", "연결 실패 broker=%s:%d rc=%d count=%u, 2초 뒤 다시", BROKER_HOST, BROKER_PORT, mqtt.state(), (unsigned)++failures);
      delay(2000);
    }
  }
}

const char* resetReasonName(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON:   return "poweron";
    case ESP_RST_EXT:       return "ext";
    case ESP_RST_SW:        return "sw";
    case ESP_RST_PANIC:     return "panic";
    case ESP_RST_INT_WDT:   return "int_wdt";
    case ESP_RST_TASK_WDT:  return "task_wdt";
    case ESP_RST_WDT:       return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT:  return "brownout";
    case ESP_RST_USB:       return "usb";
    case ESP_RST_JTAG:      return "jtag";
    default:                return "other";
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  esp_reset_reason_t reason = esp_reset_reason();
  LOGI("boot", "부팅 fw=%s model=%s device=%s reset_reason=%s heap_kb=%u psram_kb=%u",
       FW_VERSION, MODEL_VERSION, DEVICE_ID, resetReasonName(reason),
       (unsigned)(ESP.getFreeHeap() / 1024), (unsigned)(ESP.getFreePsram() / 1024));
  // 죽어서 다시 켜진 경우 (예외, 워치독, 전압 부족)
  if (reason == ESP_RST_PANIC || reason == ESP_RST_INT_WDT || reason == ESP_RST_TASK_WDT ||
      reason == ESP_RST_WDT || reason == ESP_RST_BROWNOUT) {
    LOGW("boot", "비정상 재부팅 reset_reason=%s", resetReasonName(reason));
  }

  connectWiFi();
  mqtt.setServer(BROKER_HOST, BROKER_PORT);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  if (running) {
    // TODO(face-detector): 카메라 한 장 → face-model 실행 → publishFace(face, score, count, inferMs)
  }
}
