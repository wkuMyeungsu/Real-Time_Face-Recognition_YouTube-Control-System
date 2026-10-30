# 주고받는 메시지 (MQTT 토픽)

상태: **제안**(문서만 있음) → **구현**(양쪽이 이 형식대로 구현해 dev에 병합) → **합의**(양쪽 담당자가 이 문서를 확인). 형식을 바꿀 때는 이 문서부터 고치고 양쪽 담당자에게 PR 리뷰를 받는다.

| 토픽 | 보내는 쪽 → 받는 쪽 | QoS | retain | 상태 |
|---|---|---|---|---|
| `zt/<기기>/control` | web → ESP32, processor | 1 | 아니오 | 제안 |
| `zt/<기기>/face` | ESP32 → processor | 0 | 아니오 | 제안 |
| `zt/<기기>/status` | ESP32 → web | 1 | 예 | 제안 |
| `zt/<기기>/player` | processor → web | 1 | 아니오 | 제안 |

## 공통

- `<기기>`는 보드마다 다른 ID다: `esp32-a`, `esp32-b`. 펌웨어는 `secrets.h`의 `DEVICE_ID`, web은 주소의 `?device=`, processor는 `zt/+/…`로 모든 기기를 받는다.
- 본문은 모두 JSON 객체(UTF-8)다. 형식이 틀린 메시지는 받는 쪽이 버린다.
- broker 주소: ESP32는 `<PC 내부 IP>:1883`, processor는 `broker:1883`, 브라우저는 `ws://<페이지 주소>/mqtt`.

## control — web → ESP32, processor

```json
{ "cmd": "start" }
{ "cmd": "stop" }
```

- ESP32는 `start`를 받으면 추론을 시작하고 `face`를 보낸다. `stop`이면 멈춘다. 받을 때마다 `status`를 다시 보낸다.
- processor는 둘 다 받으면 그 기기의 판정 상태를 처음으로 돌린다.
- ESP32가 재부팅되면 `idle`로 시작한다. 다시 `start`를 보내야 한다.

## face — ESP32 → processor

추론 한 번마다 하나. `running`일 때만, 최대 초당 10개.

```json
{ "seq": 123, "face": true, "score": 0.91, "count": 1, "infer_ms": 95 }
```

| 필드 | 형식 | 뜻 |
|---|---|---|
| `seq` | 정수 | 부팅 후 0부터 1씩 올림 |
| `face` | 참/거짓 | threshold를 넘은 얼굴이 하나라도 있으면 `true` |
| `score` | 실수 0~1 | 가장 높은 얼굴 점수. 없으면 0 |
| `count` | 정수 | threshold를 넘은 얼굴 수 |
| `infer_ms` | 정수 | 추론에 걸린 시간 |

재생·정지 판단은 ESP32가 하지 않는다. 프레임마다 결과만 보내고 processor가 정한다.

## status — ESP32 → web

```json
{ "state": "running", "fw": "0.1.0" }
{ "state": "idle", "fw": "0.1.0" }
{ "state": "offline" }
```

- retain이라 web이 나중에 접속해도 마지막 상태를 바로 받는다.
- `offline`은 ESP32가 MQTT 연결 때 LWT(유언 메시지)로 걸어 둔다. 연결이 끊기면 broker가 대신 보낸다.

## player — processor → web

```json
{ "action": "play" }
{ "action": "pause" }
```

- 명령이 바뀔 때만 보낸다. 같은 명령을 연달아 보내지 않는다.
- 판정 기준(`PLAY_AFTER_MS` `PAUSE_AFTER_MS` `MIN_SCORE`)은 `.env`에 있다.
