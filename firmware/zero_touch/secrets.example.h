// 이 파일을 같은 폴더에 secrets.h로 복사해서 자기 값으로 채운다. secrets.h는 커밋하지 않는다.
#pragma once

#define WIFI_SSID     "wifi-name"
#define WIFI_PASSWORD "wifi-password"

// broker를 띄운 PC의 내부 IP (ipconfig의 Wi-Fi IPv4). localhost가 아니다.
#define BROKER_HOST   "192.168.0.12"
#define BROKER_PORT   1883

// 보드마다 다르게: esp32-a, esp32-b. 토픽 zt/<DEVICE_ID>/... 에 들어간다.
#define DEVICE_ID     "esp32-a"
