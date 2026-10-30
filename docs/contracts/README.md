# 주고받는 메시지 (MQTT 토픽)

기계 검사용 스키마는 `schemas/<토픽>.schema.json`이다. 이 문서의 JSON 예시가 스키마에 맞는지 CI가 검사한다 (`tests/test_contracts.py`). 형식을 바꾸면 이 문서와 스키마를 같은 PR에서 고친다.

상태: **제안**(문서만 있음) → **구현**(양쪽이 이 형식대로 구현해 dev에 병합) → **합의**(양쪽 담당자가 이 문서를 확인). 형식을 바꿀 때는 이 문서부터 고치고 양쪽 담당자에게 PR 리뷰를 받는다.

| 토픽 | 보내는 쪽 → 받는 쪽 | QoS | retain | 상태 |
|---|---|---|---|---|
| `zt/<기기>/control` | player → face-detector, playback-decider | 1 | 아니오 | 제안 |
| `zt/<기기>/face` | face-detector → playback-decider | 0 | 아니오 | 제안 |
| `zt/<기기>/status` | face-detector → player | 1 | 예 | 제안 |
| `zt/<기기>/playback` | playback-decider → player | 1 | 아니오 | 제안 |
| `zt/<기기>/log/<파트>` | 모든 파트 → recorder | 0 | 아니오 | 제안 |
| `zt/<기기>/ping` | recorder → face-detector | 0 | 아니오 | 제안 |
| `zt/<기기>/pong` | face-detector → recorder | 0 | 아니오 | 제안 |

log·ping·pong은 디버깅용이다. 보내지 않아도 서비스는 동작하고, 받는 쪽은 recorder 하나다 (`docs/logging-design.txt`).

## 공통

- `<기기>`는 ESP32 보드마다 다른 ID다: `esp32-a`, `esp32-b`. face-detector는 `secrets.h`의 `DEVICE_ID`, player는 주소의 `?device=`, playback-decider는 `zt/+/…`로 모든 기기를 받는다.
- `server`는 기기 ID로 쓰지 않는다. 기기와 상관없는 서버 로그의 `<기기>` 자리에 쓴다 (`zt/server/log/playback-decider`).
- 본문은 모두 JSON 객체(UTF-8)다. 형식이 틀린 메시지는 받는 쪽이 버린다.
- broker 주소: face-detector는 `<PC 내부 IP>:1883`, playback-decider는 `broker:1883`, player(브라우저)는 `ws://<페이지 주소>/mqtt`.

## control — player → face-detector, playback-decider

```json
{ "cmd": "start" }
{ "cmd": "stop" }
```

- face-detector는 `start`를 받으면 감지를 시작하고 `face`를 보낸다. `stop`이면 멈춘다. 받을 때마다 `status`를 다시 보낸다.
- playback-decider는 둘 다 받으면 그 기기의 판정 상태를 처음으로 돌린다. `stop` 뒤에는 다음 `start`까지 `playback`을 보내지 않는다.
- ESP32가 재부팅되면 `idle`로 시작한다. 다시 `start`를 보내야 한다. player는 시작을 누른 뒤(중지 전) `idle`을 받으면 `start`를 자동으로 다시 보낸다 (2초에 한 번까지). 페이지를 열 때 retain으로 받은 status가 `running`이면 이미 시작된 것으로 보고 이어받는다.

## face — face-detector → playback-decider

face-model을 한 번 실행할 때마다 하나. `running`일 때만, 최대 초당 10개.

```json
{ "seq": 123, "face": true, "score": 0.91, "count": 1, "infer_ms": 95 }
```

| 필드 | 형식 | 뜻 |
|---|---|---|
| `seq` | 정수 | 부팅 후 0부터 1씩 올림 |
| `face` | 참/거짓 | threshold를 넘은 얼굴이 하나라도 있으면 `true` |
| `score` | 실수 0~1 | 가장 높은 얼굴 점수. 없으면 0 |
| `count` | 정수 | threshold를 넘은 얼굴 수 |
| `infer_ms` | 정수 | 모델 실행에 걸린 시간 |

재생·정지 판단은 face-detector가 하지 않는다. 프레임마다 결과만 보내고 playback-decider가 정한다.

## status — face-detector → player

```json
{ "state": "running", "fw": "0.1.0" }
{ "state": "idle", "fw": "0.1.0" }
{ "state": "offline" }
```

- retain이라 player가 나중에 접속해도 마지막 상태를 바로 받는다.
- `offline`은 face-detector가 MQTT에 연결할 때 LWT(유언 메시지)로 걸어 둔다. 연결이 끊기면 broker가 대신 보낸다.

## playback — playback-decider → player

```json
{ "action": "play" }
{ "action": "pause" }
```

- 명령이 바뀔 때만 보낸다. 같은 명령을 연달아 보내지 않는다.
- `start` 뒤 `face`가 `PAUSE_AFTER_MS` 동안 오지 않으면(face-detector가 멈추거나 끊김) 그동안 얼굴이 없었던 것으로 보고 `pause`를 보낸다.
- 판정 기준(`PLAY_AFTER_MS` `PAUSE_AFTER_MS` `MIN_SCORE`)은 `.env`에 있다.

## log — 모든 파트 → recorder

토픽은 `zt/<기기>/log/<파트>`다. `<파트>`는 README의 파트 이름(`face-detector`, `playback-decider`, `player`)이다. 본문은 로그 한 줄의 칸과 같다 (`docs/logging-design.txt` 3-1).

```json
{ "level": "INFO", "logger": "zt.face-detector.wifi", "where": "face-detector.ino:62", "msg": "연결됨", "up_ms": 12345, "fields": { "ip": "172.30.1.57", "rssi_dbm": -48 } }
{ "level": "WARNING", "logger": "zt.playback-decider.main", "where": "main.py:88", "msg": "seq 건너뜀", "ts_ms": 1793336707502, "fields": { "expected": 120, "got": 123, "lost": 3 } }
```

| 필드 | 형식 | 뜻 |
|---|---|---|
| `level` | `INFO` `WARNING` `ERROR` `CRITICAL` | `DEBUG`는 보내지 않는다 (시리얼·콘솔에서만) |
| `logger` | 문자열 | `zt.<파트>.<모듈>`. 예: `zt.face-detector.wifi` |
| `where` | 문자열 | 로그를 찍은 `파일:줄`. 브라우저는 `app.js:<함수 이름>` |
| `msg` | 문자열 | 사람이 읽는 짧은 문장 |
| `up_ms` | 정수 (없어도 됨) | ESP32 부팅 후 경과 시간 |
| `ts_ms` | 정수 (없어도 됨) | PC에서 도는 파트가 보낸 시각 (Unix ms). 서버 쪽은 시계가 하나라 그대로 비교한다 |
| `fields` | 객체 (없어도 됨) | `key=value`로 찍을 값. 값은 문자열·숫자·참/거짓·null. 단위는 키 끝에 (`_ms` `_kb` `_dbm` `_pct`) |

- 프레임마다 보내지 않는다. 정상 흐름은 5초 요약만 보낸다. 본 작업을 늦추지 않게 QoS 0이고, 측정 구간 밖에서 보낸다.
- 비밀번호·토큰·`.env` 값은 넣지 않는다. 키 이름에 `password` `token` `secret`이 들어간 값은 recorder가 앞 두 글자만 남기고 가린다.
- 받은 시각은 recorder가 붙인다 (PC 시계). `ts_ms`가 있으면 그 시각을 쓴다.

## ping — recorder → face-detector

```json
{ "id": 7 }
```

- recorder가 기기를 처음 봤을 때(`status`가 `idle`·`running`) 한 번, 그 뒤 30초마다 보낸다.
- face-detector는 받은 본문을 그대로 바로 `pong`으로 돌려준다.

## pong — face-detector → recorder

```json
{ "id": 7 }
```

- recorder가 ping을 보낸 시각과 pong을 받은 시각으로 왕복 시간 `rtt_ms`를 재고, `rtt_ms / 2`를 ESP32 → PC 한쪽 전송 지연으로 본다. 두 기기의 시계를 맞출 필요가 없다.
- face-detector가 `loop()`에서 늦게 돌려주면 그만큼 커진다. 그래서 `rtt_ms`는 전송 지연의 상한으로 읽는다.
