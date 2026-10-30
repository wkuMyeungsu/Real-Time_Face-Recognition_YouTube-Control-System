# recorder — 모든 파트의 로그를 한 타임라인으로

broker에 붙어 `zt/#`(control·face·status·playback·log·pong)와 broker 로그·통계(`$SYS`)를 받아, 저장소의 `logs/`에 쌓는다.
설계: `docs/logging-design.txt`, 토픽 형식: `docs/contracts/README.md`의 log·ping·pong 절.

## 보기

```bash
docker compose up --build -d
tail -f logs/zt.log                       # 사람이 읽는 한 타임라인 (Windows PowerShell: Get-Content logs/zt.log -Wait -Tail 50)
grep "device=esp32-a" logs/zt.log         # 기기 하나만
grep -E " (WARNING|ERROR|CRITICAL) " logs/zt.log   # 문제만
```

| 파일 | 내용 |
|---|---|
| `logs/zt.log` | 한 줄 형식의 타임라인. 5MB를 넘으면 `zt.log.1` … `zt.log.5`로 돌린다 |
| `logs/zt.jsonl` | 받은 메시지 원문 (JSON Lines, `t_ms` `topic` `qos` `retain` `payload`). face 원문은 여기에만 있다 |

`logs/`는 커밋하지 않는다 (`.gitignore`). 상태: `http://localhost:8002/health`, 받은 수·기기 목록: `/stats`.

## 한 줄 읽는 법

```
2026-10-30 14:22:28,805 INFO     zt.face-detector.wifi face-detector.ino:62 연결됨 device=demo-a ip=172.30.1.57 rssi_dbm=-48 up_ms=12345
└ 시각(LOG_TZ, 밀리초)   └ 레벨    └ 로거 zt.<파트>.<모듈>  └ 찍은 곳          └ 본문 + key=value
```

| 로거 | 어디서 | 무엇 |
|---|---|---|
| `zt.<파트>.*` | 각 파트가 `zt/<기기>/log/<파트>`로 보낸 로그 | 보낸 쪽의 레벨·로거·위치 그대로. 비밀값(`password` `token` `secret`)은 앞 두 글자만 |
| `zt.recorder.mqtt` | control·status·playback | `control 받음 device=… cmd=start`. 보드가 끊겨 LWT `offline`이 오면 WARNING. `retain=1`은 접속할 때 받은 지난 상태 |
| `zt.recorder.face` | face | 5초마다 기기별 요약: `msgs` `per_s`(계약: 10 이하) `face_true` `lost`(seq 건너뜀) `infer_ms_avg·max`. seq가 처음부터면(재부팅) WARNING |
| `zt.recorder.ping` | ping·pong | 기기를 처음 봤을 때(`status` idle·running)와 30초마다 ping. `rtt_ms`(왕복), `one_way_ms`≈rtt/2. pong이 없으면 한 번만 알린다 |
| `zt.broker` | mosquitto 로그, `$SYS` 통계 | 접속·끊김(`mosquitto`), 1분마다 `broker 요약 clients=… msgs_recv_per_min=…`, 토픽별 초당 메시지 수 |
| `zt.recorder.main` | recorder 자신 | 시작, broker 연결·끊김 |

시각은 recorder가 받은 시각(PC 시계)이다. PC에서 도는 파트가 `ts_ms`를 보내면 그 시각을 쓴다. ESP32는 시계가 다르므로 `up_ms`(부팅 후 경과)를 본문에 붙이고, 전송 지연은 ping 왕복으로 잰다.

## 설정 (.env)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `LOG_ENV` | `prod` | `dev`면 콘솔과 `zt.log`에 DEBUG까지 (broker 헬스체크 접속, "New connection" 줄 포함) |
| `LOG_TZ` | `Asia/Seoul` | 시각을 찍을 시간대 |
| `RECORDER_PORT` | `8002` | `/health`의 호스트 포트 (127.0.0.1에만 연다) |

간격은 환경 변수로 바꿀 수 있다: `FACE_SUMMARY_S`(5), `PING_EVERY_S`(30), `PONG_WAIT_S`(5), `SYS_SUMMARY_S`(60), `LOG_MAX_MB`(5), `LOG_BACKUPS`(5).

## 내 파트의 로그를 여기로 보내려면

- 형식: `docs/contracts/README.md`의 log 절. INFO 이상만, 프레임마다가 아니라 5초 요약으로, QoS 0.
- Python 서비스: `common/log_config.py`를 `app/log_config.py`로 그대로 복사하고 진입점에서 `setup_logging()` (C8이 같은지 검사).
- 기능 테스트: `tests/features.toml`의 D14·D15(playback-decider), P9(player), F4(face-detector)가 todo로 들어 있다. 구현하면 `done`으로 바꾼다.

## 개발

```bash
docker compose run --rm --no-deps recorder pytest -q     # 단위 테스트 (CI가 돌린다)
pytest -q tests/test_recorder.py                         # 저장소 루트에서 기능 테스트 R1~R7 (compose를 띄운 뒤)
```
