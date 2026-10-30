# 얼굴 인식 기반 유튜브 미디어 제어 (Zero-Touch Media)

화면을 보고 있으면 유튜브 영상이 재생되고, 얼굴이 사라지면 멈춘다.
ESP32-S3가 카메라 영상으로 얼굴을 직접 판단해 결과만 JSON으로 보내고, PC의 웹페이지가 그 결과로 영상을 제어한다.

## 흐름

1. PC 웹페이지에서 유튜브 영상을 고르고 **얼굴 인식 시작**을 누른다.
2. ESP32가 추론을 시작하고 프레임마다 얼굴 감지 결과를 보낸다.
3. processor가 결과를 모아 재생·정지를 정하고, 웹페이지가 영상을 재생·정지한다.

```
ESP32 ──MQTT 1883──▶ [broker] ◀──MQTT──▶ [processor]
  ▲                     ▲
  └── control ──────────┤ WebSocket (/mqtt)
                     [web: nginx] ◀── PC 브라우저
```

## 구조 · 담당 · 포트

| 폴더 | 역할 | 담당 | 호스트 포트 | 컨테이너 주소 |
|---|---|---|---|---|
| `firmware/` | 카메라, Edge Impulse 얼굴 감지, MQTT 송수신 (컨테이너 아님) | 모델: , 펌웨어:  | — | — |
| `services/broker/` | Mosquitto. 메시지 중계 | | 1883 | `broker:1883`, `broker:9001`(WebSocket) |
| `services/processor/` | face → 재생·정지 판정 | | 127.0.0.1:8001 | `http://processor:8001` |
| `services/web/` | 유튜브 플레이어, 시작·중지 버튼, `/mqtt`를 broker로 넘김 | | 127.0.0.1:8080 | `http://web` |

- 메시지 형식: `docs/contracts/README.md`
- broker 담당은 `docker-compose.yml`, `.env.example`, CI(`.github/workflows/ci.yml`)도 맡는다.

## 실행 (서버)

필요한 것: Docker Desktop (실행 중일 것), Docker Compose 2.24 이상.

```bash
cp .env.example .env
docker compose up --build -d       # 전체
docker compose up --build web      # 서비스 하나만
docker compose ps                  # 상태 (3개 모두 healthy)
docker compose down                # 종료
```

- PC 브라우저: `http://localhost:8080` (다른 보드는 `http://localhost:8080/?device=esp32-b`)
- processor 상태: `http://localhost:8001/stats`
- 호스트 포트가 다른 프로그램과 겹치면 `.env`에서 포트만 바꾼다.

처음 한 번만: ESP32가 들어오도록 Windows 방화벽에서 1883 인바운드 허용 (관리자 PowerShell)

```powershell
New-NetFirewallRule -DisplayName "zero-touch mqtt 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow
```

### 보드 없이 확인

```bash
docker compose exec -it processor python dev/fake_esp32.py
```

웹페이지에서 **얼굴 인식 시작**을 누르면 가짜 ESP32가 `face`를 보내기 시작한다. 터미널에서 Enter를 칠 때마다 얼굴 있음/없음이 바뀐다.

## 실행 (ESP32)

| 항목 | 값 |
|---|---|
| 보드 | Seeed XIAO ESP32S3 (FQBN `esp32:esp32:XIAO_ESP32S3`) |
| esp32 코어 | 3.0.7 (보드 매니저 URL `https://espressif.github.io/arduino-esp32/package_esp32_index.json`) |
| 라이브러리 | PubSubClient 2.8, ArduinoJson 7.2.1 |
| Tools → PSRAM | OPI PSRAM (카메라 사용 시) |
| Tools → Partition Scheme | 모델 크기를 보고 정해 여기에 적는다 |

1. `firmware/zero_touch/secrets.example.h`를 같은 폴더에 `secrets.h`로 복사하고 Wi-Fi, PC IP, `DEVICE_ID`를 채운다.
2. Arduino IDE에서 `firmware/zero_touch/zero_touch.ino`를 열어 업로드한다.
3. 시리얼 모니터(115200)에 `[boot] FW_VERSION=…`과 `[mqtt] 연결됨`이 나오고, 웹페이지의 ESP32 상태가 `idle`로 바뀌면 연결된 것이다.

## 브랜치

- `main`: 최종본. `dev`: 통합. 둘 다 직접 push하지 않고 PR로만 합친다.
- 작업 브랜치: `<태그>/<파트>/<기능>` — 태그는 `feature` `fix` `docs` `refactor` `chore`, 파트는 `firmware` `broker` `processor` `web` (여러 파트에 걸치면 `common`).
  예: `feature/web/youtube-player`, `fix/firmware/mqtt-reconnect`
- 작업 브랜치는 `dev`에서 만들고 `dev`로 PR을 올린다. 병합 후 삭제한다.
- 커밋 메시지: `<타입>(<파트>): <요약>`. 예: `feat(processor): 재생·정지 판정 구현`
- PR 병합은 Create a merge commit만 사용한다. CI가 통과해야 병합한다.
- `.env`, `secrets.h`, 모델 가중치(`*.onnx` `*.tflite`)는 커밋하지 않는다.
- 테스트는 자기 서비스 폴더의 `tests/`에 둔다. CI가 있는 것만 돌린다.
