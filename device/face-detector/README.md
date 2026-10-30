# face-detector — 얼굴 감지 실행

ESP32에서 카메라 프레임마다 face-model을 실행해 얼굴 감지 결과를 MQTT로 보낸다. player의 시작·중지 명령을 받아 감지를 켜고 끈다. 메시지 형식은 `docs/contracts/README.md`, 보드·IDE 설정은 루트 `README.md`의 "실행 (ESP32)".

## 파일

| 파일 | 하는 일 | 커밋 |
|---|---|---|
| `face-detector.ino` | 펌웨어 | O |
| `.env.example` | `.env` 견본 | O |
| `.env` | 내 Wi-Fi, broker 주소, `DEVICE_ID` | X |
| `gen_secrets.py` | `.env`를 읽어 `secrets.h`를 만든다 | O |
| `secrets.h` | `gen_secrets.py`가 만든 결과. 직접 고치지 않는다 | X |
| `secrets.example.h` | `secrets.h` 형식 견본. CI는 이걸 복사해 컴파일한다 | O |
| `tests/` | PC에서 도는 Python 코드(`gen_secrets.py` 등)의 pytest. CI가 자동으로 돌린다 | O |

## 설정 (.env)

```bash
cd device/face-detector
cp .env.example .env      # 값 채우기
python gen_secrets.py     # → secrets.h
```

`.env`를 고치면 `gen_secrets.py`를 다시 실행하고 업로드한다.

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

## 지금 상태

- 됨: Wi-Fi·MQTT 연결, `status` 발행(끊기면 `offline`), `control`(start/stop) 수신
- 안 됨: 카메라 촬영, face-model 실행 (`loop()`의 TODO)
