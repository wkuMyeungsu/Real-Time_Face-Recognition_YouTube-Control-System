# CI/CD

**CI는 빈 그릇부터, CD는 초록불 다음에.** CI는 PR마다 "합쳐도 되나"를 검사하고, CD는 CI를 통과한 main을 누구나 같은 것으로 받을 수 있게 내보낸다. 처음 구축 순서는 [ci-setup-guide.txt](ci-setup-guide.txt).

## 팀원에게 전할 규칙

1. **테스트는 자기 폴더의 `tests/`에 둔다.** CI가 있는 것만 돌린다 (`services/<서비스>/tests/` → 컨테이너 안에서 `pytest -q`, `device/<파트>/tests/` → face-detector 잡에서 `pytest -q`).
2. **CI가 초록불이어야 병합된다.** 브랜치 보호 규칙으로 강제하고, 최신 dev 위에서 통과해야 한다 ("이전 버전이 통과한 다음에 올라온다").
3. **기능을 완성하면 `tests/features.toml`에서 그 기능을 `done`으로 바꾼다.** 같은 PR에 넣는다 (아래).

## PR 하나가 지나가는 길

```
PR → server        : compose build → up --wait → services/*/tests 있는 것만
                     → 기능 목록이 뒤로 가지 않았나 → 저장소 루트 tests/ (계약 기준 기능 테스트 + smoke)
   → face-detector : device/*/tests 있는 것만 → README 환경 표 그대로 컴파일 (esp32 3.3.12, PSRAM=opi, PubSubClient 2.8, ArduinoJson 7.2.1)
   → 둘 다 초록불 + 최신 dev 위 → 병합
```

## 계약 기준 기능 테스트: 저장소 루트 `tests/`

`docs/contracts/README.md`(토픽·형식·QoS·retain), README(실행·환경), `.env.example`(판정 기준)을 기준으로 모든 파트의 기능 테스트를 **미리** 넣어 두었다. 각 테스트는 `@pytest.mark.feature("D3")`처럼 기능 번호에 묶이고, 기능 목록은 `tests/features.toml`이다.

| 상태 | 테스트가 실패하면 | 테스트가 통과하면 |
|---|---|---|
| `todo` (아직 안 만든 기능) | CI 통과 (미구현) | **CI 실패** → `done`으로 바꾸라는 뜻 |
| `done` (만든 기능) | **CI 실패** → 병합 불가 | CI 통과 |

- `done`은 되돌릴 수 없다. `done`을 `todo`로 바꾸거나 기능을 지우는 PR은 CI가 막는다 (`tests/check_features.py`). 기능이 `done`이 될 때마다 깨지지 않는 범위가 넓어진다.
- `todo`에서 봐주는 실패는 기능이 동작하지 않아 생기는 실패(검사 불일치, 시간 초과, 연결 실패)뿐이다. 테스트 코드 자체의 실수는 오류로 드러난다.
- CI 실행 화면의 Summary와 터미널 끝에 파트별 진행 상황이 나온다.

| 파트 | 기능 | 테스트 파일 | 지금 |
|---|---|---|---|
| broker | B1 주고받기, B2 status retain, B3 LWT offline, B4 WebSocket(/mqtt) | `test_broker.py` | 완료 4/4 |
| recorder | R1 /health, R2 한 줄 형식, R3 log 토픽 그대로·비밀값 가림, R4 face 5초 요약, R5 ping·pong rtt, R6 LWT offline WARNING, R7 broker 로그 | `test_recorder.py` | 완료 7/7 |
| 계약·설정 | C1~C4 스키마·문서 예시·토픽 표, C5 ESP32 환경 표 = CI·CD, C6 설정 파일, C7 기능 목록, C8 공통 로그 설정 복사본 | `test_contracts.py` | 완료 8/8 |
| playback-decider | D1 /health, D2 /stats, D3~D6 재생·정지 시간, D7 MIN_SCORE, D8 바뀔 때만·QoS·retain, D9 control 리셋, D10 기기별, D11 틀린 메시지, D12 판정 로그(reason), D13 공통 로그 설정 | `test_playback_decider.py` | 완료 11/13 |
| player | P1 /health, P2 요소 id, P3 /mqtt, P4 연결 표시, P5·P6 시작·중지, P7 ESP32 상태, P8 playback → 유튜브, P9 log 토픽 | `test_player.py` | 완료 7/9 |
| face-detector | F1 secrets.example.h, F2 부팅 때 FW_VERSION, F3 토픽·LWT, F4 LOG 매크로·log 토픽·ping → pong | `test_face_detector.py` | 완료 3/4 |
| face-model | M1 Edge Impulse 라이브러리 | `test_face_detector.py` | 0/1 |
| 전체 | E1 smoke (start → face → play → pause), E2 player 버튼 → 유튜브 | `smoke/test_smoke.py` | 완료 1/2 |

### 내 기능을 완성했을 때

```bash
cp .env.example .env && docker compose up --build -d
pip install -r tests/requirements.txt
python -m playwright install chromium     # player 테스트용 (처음 한 번)
pytest -q tests/                          # 끝에 파트별 진행 상황
```

내 기능이 "! 통과함 → done으로 바꾸기"로 나오면 `tests/features.toml`에서 그 기능을 `"done"`으로 바꿔 구현과 같은 PR에 넣는다. 계약을 바꿔야 하면 `docs/contracts/README.md`, `docs/contracts/schemas/`, 테스트, `features.toml`을 같은 PR에서 고치고 양쪽 담당자에게 리뷰를 받는다.

## CD: 초록불 받은 main을 내보낸다 (Continuous Delivery)

| 신호 | 하는 일 | 결과물 |
|---|---|---|
| main 병합 | playback-decider·player·recorder 이미지 빌드 → ghcr.io push (tag = 커밋 SHA, `main`) | `ghcr.io/<저장소>/playback-decider:<SHA>`, `…/player:<SHA>`, `…/recorder:<SHA>` |
| `v*` 태그 (`git tag v1.0 && git push origin v1.0`) | face-detector를 README 환경 표 그대로 컴파일 → Release에 첨부 | GitHub Releases의 `.bin` |

broker는 공식 이미지와 저장소의 `mosquitto.conf`로 뜨므로 따로 올리지 않는다. 결과물을 올리는 데까지만 자동이고, 데모 PC에서 실행하는 것은 사람이 한다.

### 데모 PC에서

```bash
git clone <저장소> && cd <저장소> && cp .env.example .env
TAG=<커밋 SHA> docker compose pull
TAG=<커밋 SHA> docker compose up -d      # 빌드하지 않고 CI를 통과한 이미지 그대로
pytest -q tests/smoke                    # 시연 전 마지막 확인 (pip install -r tests/requirements.txt)
```

- SHA는 Actions의 cd 실행 화면 Summary에 나온다. 가장 최근 main은 `TAG=main`.
- ghcr.io 이미지는 처음에 비공개일 수 있다. 저장소 주인이 GitHub → Packages → 이미지 → Package settings → Change visibility → Public으로 한 번 바꾸면 로그인 없이 받는다.
- 펌웨어 `.bin`은 예시 `secrets.h`로 컴파일된 것이라 Wi-Fi·broker 주소가 예시 값이다. 실제 보드에는 각자 `secrets.h`를 채워 Arduino IDE로 올린다. Release는 "main에서 통과한 펌웨어가 이 버전"이라는 기록이다.

## 저장소 설정 (저장소 주인이 한 번, CI가 한 번 돈 뒤)

Settings → Branches → Add branch protection rule (`main`, `dev` 각각)

- Require a pull request before merging
- Require status checks to pass before merging → `server`, `face-detector`
- Require branches to be up to date before merging

Settings → General → Pull Requests: Allow merge commits만 켜고 squash·rebase는 끈다.
