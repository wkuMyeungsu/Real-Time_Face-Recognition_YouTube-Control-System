// face-detector: ESP32에서 카메라 프레임마다 face-model을 실행해 얼굴 감지 결과를 보낸다. Wi-Fi·MQTT 연결, status 발행, control(start/stop) 받기.
// 카메라 촬영과 face-model 실행은 아직 없다. loop()의 TODO 자리에서 publishFace()를 부른다.
// 메시지 형식은 docs/contracts/README.md.

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "secrets.h"  // .env를 채운 뒤 python gen_secrets.py로 만든다 (커밋하지 않음)

#define FW_VERSION "0.1.0"

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
  if (deserializeJson(doc, payload, len)) return;
  const char* cmd = doc["cmd"] | "";
  if (strcmp(cmd, "start") == 0) running = true;
  else if (strcmp(cmd, "stop") == 0) running = false;
  else return;
  Serial.printf("[control] %s\n", cmd);
  publishStatus();
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[wifi] 연결 중");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[wifi] %s\n", WiFi.localIP().toString().c_str());
}

void connectMqtt() {
  while (!mqtt.connected()) {
    Serial.printf("[mqtt] %s:%d 연결 중\n", BROKER_HOST, BROKER_PORT);
    // LWT: 보드가 끊기면 broker가 대신 offline을 retain으로 남긴다
    if (mqtt.connect(DEVICE_ID, topicStatus.c_str(), 1, true, "{\"state\":\"offline\"}")) {
      mqtt.subscribe(topicControl.c_str(), 1);
      publishStatus();
      Serial.println("[mqtt] 연결됨");
    } else {
      Serial.printf("[mqtt] 실패 rc=%d, 2초 뒤 다시\n", mqtt.state());
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.printf("[boot] FW_VERSION=%s DEVICE_ID=%s\n", FW_VERSION, DEVICE_ID);

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
