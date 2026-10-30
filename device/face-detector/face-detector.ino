// face-detector: ESP32에서 카메라 프레임마다 face-model을 실행해 얼굴 감지 결과를 보낸다. Wi-Fi·MQTT 연결, status 발행, control(start/stop) 받기.
// 카메라·모델 실행은 face_runner.cpp. running일 때 최대 초당 10장 돌려 face를 보낸다.
// 메시지 형식은 docs/contracts/README.md. 시리얼 로그 형식은 log.h. INFO 이상 로그는 log 토픽으로도 보낸다.

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "secrets.h"  // .env를 채운 뒤 python gen_secrets.py로 만든다 (커밋하지 않음)
#include "log.h"
#include "face_runner.h"
#include "preview_server.h"  // 브라우저로 http://<보드 IP>/ 를 열면 카메라 화면과 얼굴 박스가 보인다

#define FW_VERSION "0.3.0"
#define WEAK_RSSI_DBM -75          // 이보다 약하면 WARNING
#define WIFI_WAIT_WARN_MS 10000    // Wi-Fi 연결을 이만큼 기다릴 때마다 WARNING
#define FRAME_INTERVAL_MS 100      // 계약: face는 초당 최대 10개
#define SUMMARY_INTERVAL_MS 5000   // running일 때 5초마다 요약 로그
#define SLOW_INFER_MS 200          // 이보다 느리면 WARNING
#define MQTT_BUFFER_SIZE 1024      // log 메시지가 PubSubClient 기본 버퍼(256)보다 길다
#define LOG_QUEUE_SIZE 8           // MQTT 연결 전에 남긴 로그(부팅·Wi-Fi)를 연결되면 보낸다
#define LOG_JSON_SIZE 384
#define LED_PIN 21                 // 사용자 LED (LOW = 켜짐). 얼굴이 보이면 켠다

WiFiClient net;
PubSubClient mqtt(net);

String topicControl = String("zt/") + DEVICE_ID + "/control";
String topicFace    = String("zt/") + DEVICE_ID + "/face";
String topicStatus  = String("zt/") + DEVICE_ID + "/status";
String topicLog     = String("zt/") + DEVICE_ID + "/log/face-detector";
String topicPing    = String("zt/") + DEVICE_ID + "/ping";
String topicPong    = String("zt/") + DEVICE_ID + "/pong";

bool running = false;
bool modelReady = false;
uint32_t seq = 0;

// 5초 요약용
struct FrameStats {
  uint32_t frames, faces, dropped;
  uint32_t captureSum, captureMax, inferSum, inferMax;
} stats;
unsigned long statsSince = 0;

void resetStats() {
  stats = {};
  statsSince = millis();
}

// ───────── log 토픽 (docs/contracts/README.md "log") ─────────

char logQueue[LOG_QUEUE_SIZE][LOG_JSON_SIZE];
uint8_t logQueueHead = 0, logQueueCount = 0;

bool isFieldKey(const char* token, const char* eq) {
  if (eq == token || !(islower(*token) || *token == '_')) return false;
  for (const char* p = token; p < eq; p++) {
    if (!(islower(*p) || isdigit(*p) || *p == '_')) return false;
  }
  return true;
}

void setField(JsonObject fields, const char* key, const char* value) {
  char* end;
  if (strcmp(value, "true") == 0) fields[key] = true;
  else if (strcmp(value, "false") == 0) fields[key] = false;
  else if (*value && (strtol(value, &end, 10), *end == '\0')) fields[key] = strtol(value, nullptr, 10);
  else if (*value && (strtod(value, &end), *end == '\0')) fields[key] = strtod(value, nullptr);
  else fields[key] = value;
}

// "연결됨 ssid=KT 2G ip=1.2.3.4 rssi_dbm=-48" → msg "연결됨", fields {ssid:"KT 2G", ip:"1.2.3.4", rssi_dbm:-48}
// 첫 key=value 앞까지가 msg, 그 뒤 key=value가 아닌 토큰은 앞 값에 공백으로 이어 붙인다 (SSID에 공백이 있을 때).
size_t buildLogJson(char* out, size_t outSize, int level, const char* module, const char* file, int line, const char* text) {
  char buf[192];
  strlcpy(buf, text, sizeof buf);
  const int MAX_TOKENS = 32;
  char* tokens[MAX_TOKENS];
  bool isKey[MAX_TOKENS];
  int n = 0, firstKey = -1;
  for (char* t = strtok(buf, " "); t && n < MAX_TOKENS; t = strtok(nullptr, " ")) {
    char* eq = strchr(t, '=');
    isKey[n] = eq && isFieldKey(t, eq);
    if (isKey[n] && firstKey < 0) firstKey = n;
    tokens[n++] = t;
  }
  int msgEnd = firstKey < 0 ? n : firstKey;
  // strtok이 공백 자리에 넣은 '\0'을 되돌려 msg와 값을 이어 붙인다
  for (int i = 1; i < n; i++) {
    bool joinMsg = i < msgEnd;
    bool joinValue = firstKey >= 0 && i > firstKey && !isKey[i];
    if (joinMsg || joinValue) tokens[i][-1] = ' ';
  }

  JsonDocument doc;
  char logger[48], where[48];
  snprintf(logger, sizeof logger, "zt.face-detector.%s", module);
  snprintf(where, sizeof where, "%s:%d", file, line);
  doc["level"] = ztLogLevelName(level);
  doc["logger"] = logger;
  doc["where"] = where;
  doc["msg"] = msgEnd > 0 ? tokens[0] : "로그";
  doc["up_ms"] = millis();
  if (firstKey >= 0) {
    JsonObject fields = doc["fields"].to<JsonObject>();
    for (int i = firstKey; i < n; i++) {
      if (!isKey[i]) continue;
      char* eq = strchr(tokens[i], '=');
      *eq = '\0';
      setField(fields, tokens[i], eq + 1);
    }
  }
  return serializeJson(doc, out, outSize);
}

void publishLogLine(const char* json, size_t len) {
  mqtt.publish(topicLog.c_str(), (const uint8_t*)json, len, false);  // QoS 0
}

void logToMqtt(int level, const char* module, const char* file, int line, const char* msg) {
  char json[LOG_JSON_SIZE];
  size_t len = buildLogJson(json, sizeof json, level, module, file, line, msg);
  if (mqtt.connected()) {
    publishLogLine(json, len);
    return;
  }
  // 연결 전이면 모아 뒀다가 연결되면 보낸다. 넘치면 가장 오래된 것부터 버린다
  uint8_t slot = (logQueueHead + logQueueCount) % LOG_QUEUE_SIZE;
  if (logQueueCount == LOG_QUEUE_SIZE) logQueueHead = (logQueueHead + 1) % LOG_QUEUE_SIZE;
  else logQueueCount++;
  strlcpy(logQueue[slot], json, LOG_JSON_SIZE);
}

void flushLogQueue() {
  while (logQueueCount && mqtt.connected()) {
    publishLogLine(logQueue[logQueueHead], strlen(logQueue[logQueueHead]));
    logQueueHead = (logQueueHead + 1) % LOG_QUEUE_SIZE;
    logQueueCount--;
  }
}

// ───────── MQTT 메시지 ─────────

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
  // ping은 받은 본문 그대로 바로 pong (recorder가 왕복 시간을 잰다). publish가 받은 버퍼를 덮어쓰므로 먼저 복사한다
  if (topicPing == topic) {
    uint8_t body[64];
    unsigned int n = min(len, (unsigned int)sizeof body);
    memcpy(body, payload, n);
    mqtt.publish(topicPong.c_str(), body, n, false);
    return;
  }

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
  if (running) resetStats();
  else digitalWrite(LED_PIN, HIGH);
  publishStatus();
}

// ───────── 연결 ─────────

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
      mqtt.subscribe(topicPing.c_str(), 0);
      publishStatus();
      connectedBefore = true;
      LOGI("mqtt", "연결됨 broker=%s:%d client_id=%s", BROKER_HOST, BROKER_PORT, DEVICE_ID);
      flushLogQueue();
    } else {
      LOGW("mqtt", "연결 실패, 2초 뒤 다시 broker=%s:%d rc=%d count=%u", BROKER_HOST, BROKER_PORT, mqtt.state(), (unsigned)++failures);
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

// ───────── 감지 ─────────

void detectOnce() {
  FaceResult r;
  if (!runFaceModel(r)) {
    stats.dropped++;
    return;
  }
  publishFace(r.face, r.score, r.count, r.inferMs);  // 측정이 끝난 뒤 보낸다
  digitalWrite(LED_PIN, r.face ? LOW : HIGH);
  stats.frames++;
  if (r.face) stats.faces++;
  stats.captureSum += r.captureMs;
  stats.inferSum += r.inferMs;
  stats.captureMax = max(stats.captureMax, r.captureMs);
  stats.inferMax = max(stats.inferMax, r.inferMs);
  LOGD("infer", "프레임 seq=%u face=%s score=%.2f count=%d capture_ms=%u infer_ms=%u",
       (unsigned)(seq - 1), r.face ? "true" : "false", r.score, r.count, (unsigned)r.captureMs, (unsigned)r.inferMs);
}

void logSummary() {
  static uint32_t lastHeapKb = 0, heapDropStreak = 0;
  float sec = (millis() - statsSince) / 1000.0f;
  uint32_t n = stats.frames ? stats.frames : 1;
  uint32_t heapKb = ESP.getFreeHeap() / 1024;
  LOGI("infer", "5초 요약 frames=%u fps=%.1f faces=%u dropped=%u capture_ms_avg=%u capture_ms_max=%u infer_ms_avg=%u infer_ms_max=%u heap_kb=%u",
       (unsigned)stats.frames, stats.frames / sec, (unsigned)stats.faces, (unsigned)stats.dropped,
       (unsigned)(stats.captureSum / n), (unsigned)stats.captureMax,
       (unsigned)(stats.inferSum / n), (unsigned)stats.inferMax, (unsigned)heapKb);
  if (stats.inferMax > SLOW_INFER_MS) LOGW("infer", "추론 느림 infer_ms_max=%u", (unsigned)stats.inferMax);

  heapDropStreak = (lastHeapKb && heapKb < lastHeapKb) ? heapDropStreak + 1 : 0;
  if (heapDropStreak == 3) LOGW("boot", "남은 메모리가 계속 줄어듦 heap_kb=%u", (unsigned)heapKb);
  lastHeapKb = heapKb;
  resetStats();
}

// ───────── setup / loop ─────────

void setup() {
  Serial.begin(115200);
  delay(1000);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);
  ztSetLogSink(logToMqtt);  // 연결 전 로그는 모아 뒀다가 연결되면 보낸다

  esp_reset_reason_t reason = esp_reset_reason();
  LOGI("boot", "부팅 fw=%s model=%s device=%s reset_reason=%s heap_kb=%u psram_kb=%u",
       FW_VERSION, faceModelVersion(), DEVICE_ID, resetReasonName(reason),
       (unsigned)(ESP.getFreeHeap() / 1024), (unsigned)(ESP.getFreePsram() / 1024));
  // 죽어서 다시 켜진 경우 (예외, 워치독, 전압 부족)
  if (reason == ESP_RST_PANIC || reason == ESP_RST_INT_WDT || reason == ESP_RST_TASK_WDT ||
      reason == ESP_RST_WDT || reason == ESP_RST_BROWNOUT) {
    LOGW("boot", "비정상 재부팅 reset_reason=%s", resetReasonName(reason));
  }

  // 카메라·모델이 안 되어도 Wi-Fi·MQTT·status는 계속 돈다 (CRITICAL 로그로 알린다)
  modelReady = faceModelBegin();

  mqtt.setBufferSize(MQTT_BUFFER_SIZE);
  connectWiFi();
  if (modelReady) startPreviewServer();
  mqtt.setServer(BROKER_HOST, BROKER_PORT);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  if (!running || !modelReady) return;
  static unsigned long lastFrame = 0;
  if (millis() - lastFrame >= FRAME_INTERVAL_MS) {
    lastFrame = millis();
    detectOnce();
  }
  if (millis() - statsSince >= SUMMARY_INTERVAL_MS) logSummary();
}
