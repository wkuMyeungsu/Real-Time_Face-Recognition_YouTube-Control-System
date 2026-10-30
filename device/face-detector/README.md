# face-detector — 얼굴 감지 실행

ESP32에서 카메라 프레임마다 face-model을 실행해 얼굴 감지 결과를 MQTT로 보낸다. player의 시작·중지 명령을 받아 감지를 켜고 끈다. 메시지 형식은 `docs/contracts/README.md`, 보드·IDE 설정은 루트 `README.md`의 "실행 (ESP32)".

## 파일

| 파일 | 하는 일 | 커밋 |
|---|---|---|
| `face-detector.ino` | 펌웨어 | O |
| `log.h` | 시리얼 로그 매크로 (`LOGD` `LOGI` `LOGW` `LOGE` `LOGC`). 팀 공통 로그 형식 | O |
| `sketch.yaml` | esp32 코어·라이브러리 버전 (Python의 `requirements.txt` 같은 것) | O |
| `setup_arduino.py` | 업로드 전 준비: 코어·라이브러리 설치, `secrets.h` 생성, 보드 포트 확인 | O |
| `detect_network.py` | 이 PC가 붙은 Wi-Fi의 SSID·비밀번호와 Wi-Fi IP를 찾는다 (Windows). `setup_arduino.py`가 쓴다 | O |
| `.env.example` | `.env` 견본 | O |
| `.env` | 내 Wi-Fi, broker 주소, `DEVICE_ID` | X |
| `gen_secrets.py` | `.env`를 읽어 `secrets.h`를 만든다 | O |
| `secrets.h` | `gen_secrets.py`가 만든 결과. 직접 고치지 않는다 | X |
| `secrets.example.h` | `secrets.h` 형식 견본. CI는 이걸 복사해 컴파일한다 | O |
| `tests/` | PC에서 도는 Python 코드(`gen_secrets.py`, `setup_arduino.py`, `detect_network.py`)의 pytest. CI가 자동으로 돌린다 | O |

## 처음 한 번 (setup_arduino.py)

```bash
cd device/face-detector
cp .env.example .env        # 값 채우기
python setup_arduino.py     # 보드를 USB로 꽂은 뒤
```

| 단계 | 하는 일 | 빠졌을 때 |
|---|---|---|
| 1/3 | `sketch.yaml`의 esp32 코어·라이브러리를 Arduino IDE에 설치 (IDE에 들어 있는 arduino-cli를 쓴다) | IDE를 못 찾으면 환경 변수 `ARDUINO_CLI`에 arduino-cli 경로를 넣으라고 알려 준다 |
| 2/3 | `.env`로 `secrets.h` 생성. `.env`가 없거나 Wi-Fi·broker 값이 비었으면 이 PC의 Wi-Fi 정보(SSID·비밀번호·IP)를 찾아 보여 주고, 확인을 받아 채운다. PC가 5G에 붙어 있으면 같은 공유기의 2G SSID를 고른다 | 찾지 못했거나 거절하면 어느 키를 직접 채울지 알려 준다 |
| 3/3 | ESP32가 꽂힌 포트 표시 | 연결이 안 보이면 케이블·BOOT 버튼 확인을 안내한다 |

Wi-Fi 자동 채우기는 broker를 띄우는 PC에서 실행할 때만 맞다. 서버를 다른 PC에서 띄우면 그 PC의 Wi-Fi·IP를 `.env`에 직접 적는다.

빠진 것이 있으면 끝에 실패(exit 1)로 끝난다. 버전을 바꿀 때는 `sketch.yaml`, 루트 README "개발 환경" 표, `.github/workflows/ci.yml`을 같이 고친다 (`tests/`가 셋이 같은지 검사한다).

## 설정 (.env)

`.env`를 고치면 `python gen_secrets.py`로 `secrets.h`만 다시 만들고 업로드한다.

| 키 | 값 |
|---|---|
| `WIFI_SSID` `WIFI_PASSWORD` | 2.4GHz Wi-Fi. ESP32-S3는 5G에 붙지 않는다 |
| `BROKER_HOST` | broker를 띄운 PC의 내부 IP (`ipconfig`의 Wi-Fi IPv4). `localhost`가 아니다. ESP32와 같은 네트워크여야 한다 |
| `BROKER_PORT` | 1883 |
| `DEVICE_ID` | 보드마다 다르게: `esp32-a`, `esp32-b` |

루트의 `.env`(docker compose용)와는 다른 파일이다. Wi-Fi 비밀번호가 서버 컨테이너로 넘어가지 않도록 따로 둔다.

## 테스트

`tests/`에 `test_*.py`를 넣으면 CI가 돌린다. pytest 말고 필요한 라이브러리는 이 폴더의 `requirements-dev.txt`에 적는다. 펌웨어(`.ino`)는 CI에서 컴파일만 검사한다.

```bash
cd device/face-detector
python -m pytest -q tests
```

## 로그

시리얼 출력은 모두 `log.h`의 매크로로 한다 (`Serial.print`를 직접 쓰지 않는다. `tests/`가 검사한다). 형식은 팀 공통(수업 Day11 logging 형식)이고, 시각 자리에는 부팅 후 경과 시간을 찍는다.

```
[up 1016ms] INFO     zt.face-detector.boot face-detector.ino:133 부팅 fw=0.2.0 model=none device=esp32-a reset_reason=usb heap_kb=308 psram_kb=8189
[up 3564ms] INFO     zt.face-detector.wifi face-detector.ino:85 연결됨 ssid=… ip=172.30.1.48 rssi_dbm=-65 connect_ms=2500
[up 3970ms] INFO     zt.face-detector.mqtt face-detector.ino:103 연결됨 broker=172.30.1.81:1883 client_id=esp32-a
[up 101190ms] ERROR    zt.face-detector.mqtt face-detector.ino:58 잘못된 메시지 topic=zt/esp32-a/control reason=unknown_cmd cmd=jump
```

- 쓰는 법: `LOGI("wifi", "연결됨 ip=%s rssi_dbm=%d", ip, rssi)`. 첫 인자는 로거 이름 마지막 칸(`boot` `wifi` `mqtt` `camera` `infer`).
- 메시지는 한국어 한 문장 + `key=value`, 단위는 키 끝(`_ms` `_kb` `_dbm`). 비밀번호는 찍지 않는다.
- 기본은 INFO 이상만 찍는다. 자세히 보려면 `#include "log.h"` 앞에 `#define ZT_LOG_LEVEL ZT_LOG_DEBUG`.
- 레벨 기준: 정상 흐름 INFO, 재연결·신호 약함(`rssi_dbm` < -75)·비정상 재부팅 WARNING, 잘못된 메시지 ERROR.
- MQTT `log` 토픽으로 보내기와 `ping`/`pong`은 계약 합의 후에 넣는다.

## 지금 상태

- 됨: Wi-Fi·MQTT 연결, `status` 발행(끊기면 `offline`), `control`(start/stop) 수신, 공통 형식 시리얼 로그
- 안 됨: 카메라 촬영, face-model 실행 (`loop()`의 TODO)
