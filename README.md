# 얼굴 인식 기반 유튜브 미디어 제어 (Zero-Touch Media)

화면을 보고 있으면 유튜브 영상이 재생되고, 얼굴이 사라지면 멈춘다.
ESP32-S3가 카메라 영상으로 얼굴을 직접 판단해 결과만 JSON으로 보내고, PC의 웹페이지가 그 결과로 영상을 제어한다.

## 흐름

1. player(PC 웹페이지)에서 유튜브 영상을 고르고 **얼굴 인식 시작**을 누른다.
2. face-detector(ESP32)가 카메라 프레임마다 face-model을 실행해 감지 결과를 보낸다.
3. playback-decider가 결과를 모아 재생·정지를 정하고, player가 영상을 재생·정지한다.

```
[face-detector: ESP32] ──MQTT 1883──▶ [broker] ◀──MQTT──▶ [playback-decider]
        ▲                               ▲
        └──── control ──────────────────┤ WebSocket (/mqtt)
                                   [player: nginx] ◀── PC 브라우저
```

## 파트 · 담당 · 포트

| 파트 | 하는 일 | 폴더 | 담당 | 호스트 포트 | 컨테이너 주소 |
|---|---|---|---|---|---|
| `face-model` | 얼굴 감지 모델. Edge Impulse에서 만들고 threshold를 정해 Arduino 라이브러리로 내보낸다 | `device/face-model/` | 김대희 | — | — |
| `face-detector` | 얼굴 감지 실행. ESP32에서 카메라 → face-model 실행 → 결과 송신, 시작·중지 명령 수신 | `device/face-detector/` | 박명수 | — | — |
| `broker` | MQTT 브로커(Mosquitto)와 실행 환경(compose, `.env`, CI, 계약 문서) | `services/broker/`, 저장소 루트 | 임우진 | 1883 | `broker:1883`, `broker:9001`(WebSocket) |
| `playback-decider` | 재생 판정. face 결과를 모아 재생·정지를 정한다 | `services/playback-decider/` | 김도은 | 127.0.0.1:8001 | `http://playback-decider:8001` |
| `player` | 재생 화면. 유튜브 플레이어, 시작·중지 버튼, 판정대로 재생·정지 실행, `/mqtt`를 broker로 넘김 | `services/player/` | 이진아 | 127.0.0.1:8080 | `http://player` |

- 메시지 형식: `docs/contracts/README.md`
- broker 사용법·메시지 보기·접속 문제 해결: `services/broker/README.md`
- CI 구축 안내: `docs/ci-setup-guide.txt`

## 실행 (서버)

필요한 것: Docker Desktop (실행 중일 것), Docker Compose 2.24 이상.

```bash
cp .env.example .env
docker compose up --build -d          # 전체
docker compose up --build player      # 서비스 하나만
docker compose ps                     # 상태 (3개 모두 healthy)
docker compose down                   # 종료
```

- PC 브라우저: `http://localhost:8080` (다른 보드는 `http://localhost:8080/?device=esp32-b`)
- playback-decider 상태: `http://localhost:8001/stats`
- 호스트 포트가 다른 프로그램과 겹치면 `.env`에서 포트만 바꾼다.

처음 한 번만: ESP32가 들어오도록 Windows 방화벽에서 1883 인바운드 허용 (관리자 PowerShell)

```powershell
New-NetFirewallRule -DisplayName "zero-touch mqtt 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow
```

### 보드 없이 확인

```bash
docker compose exec -it playback-decider python dev/fake_face_detector.py
```

player에서 **얼굴 인식 시작**을 누르면 가짜 face-detector가 `face`를 보내기 시작한다. 터미널에서 Enter를 칠 때마다 얼굴 있음/없음이 바뀐다.

## 실행 (ESP32)

### 하드웨어

| 부품 | 모델 |
|---|---|
| 보드 | Seeed XIAO ESP32S3 (Wi-Fi 2.4GHz 내장) |
| 카메라 | OV3660 (XIAO 카메라 커넥터에 연결, 핀 배치는 `CAMERA_MODEL_XIAO_ESP32S3`) |
| 안테나 | Seeed Studio 2.4G 외부 안테나 (A-02). 보드의 U.FL 단자에 꽂는다 |

### 개발 환경

| 항목 | 값 |
|---|---|
| Arduino IDE | 2.3.10 |
| Tools → Board | XIAO_ESP32S3 (FQBN `esp32:esp32:XIAO_ESP32S3`) |
| esp32 코어 | 3.3.12 (보드 매니저 URL `https://espressif.github.io/arduino-esp32/package_esp32_index.json`) |
| 라이브러리 | PubSubClient 2.8, ArduinoJson 7.2.1 (`device/face-detector/sketch.yaml`) |
| Tools → PSRAM | OPI PSRAM (카메라에 필요) |
| Tools → Partition Scheme | face-model 크기를 보고 정해 여기에 적는다 |

1. `device/face-detector/.env.example`을 같은 폴더에 `.env`로 복사해 Wi-Fi(2.4GHz), PC IP, `DEVICE_ID`를 채운다.
2. 보드를 USB로 꽂고 그 폴더에서 `python setup_arduino.py`를 실행한다. esp32 코어·라이브러리 설치(버전은 `sketch.yaml`), `secrets.h` 생성, 보드 포트 확인을 한 번에 한다. 빠진 것이 있으면 무엇을 할지 알려 준다. 자세한 내용은 `device/face-detector/README.md`.
3. Arduino IDE에서 `device/face-detector/face-detector.ino`를 열고 2에서 알려 준 포트를 골라 업로드한다.
4. 시리얼 모니터(115200)에 `[boot] FW_VERSION=…`과 `[mqtt] 연결됨`이 나오고, player의 ESP32 상태가 `idle`로 바뀌면 연결된 것이다.

## 브랜치

- `main`: 최종본. `dev`: 통합. 둘 다 직접 push하지 않고 PR로만 합친다.
- 작업 브랜치: `<태그>/<파트>/<기능>` — 태그는 `feature` `fix` `docs` `refactor` `chore`, 파트는 `face-model` `face-detector` `broker` `playback-decider` `player` (여러 파트에 걸치면 `common`).
  예: `feature/player/youtube-iframe`, `fix/face-detector/mqtt-reconnect`
- 작업 브랜치는 `dev`에서 만들고 `dev`로 PR을 올린다. 병합 후 삭제한다.
- 커밋 메시지: `<타입>(<파트>): <요약>`. 예: `feat(playback-decider): 재생·정지 판정 구현`
- PR 병합은 Create a merge commit만 사용한다. CI가 통과해야 병합한다.
- `.env`, `secrets.h`, 모델 가중치(`*.onnx` `*.tflite`)는 커밋하지 않는다.
- 테스트는 자기 폴더의 `tests/`에 둔다 (`services/<서비스>/tests/`, `device/<파트>/tests/`). CI가 있는 것만 돌린다.
