// secrets.h 형식 견본. 실제 secrets.h는 .env를 채운 뒤 python gen_secrets.py로 만든다 (커밋하지 않음). CI는 이 파일을 복사해 컴파일한다.
#pragma once

#define WIFI_SSID     "wifi-name"
#define WIFI_PASSWORD "wifi-password"

// broker를 띄운 PC의 내부 IP (ipconfig의 Wi-Fi IPv4). localhost가 아니다.
#define BROKER_HOST   "192.168.0.12"
#define BROKER_PORT   1883

// 보드마다 다르게: esp32-a, esp32-b. 토픽 zt/<DEVICE_ID>/... 에 들어간다.
#define DEVICE_ID     "esp32-a"
