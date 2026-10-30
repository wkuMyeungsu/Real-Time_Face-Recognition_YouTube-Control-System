# face-model 작업 기록

2026-10-30 · 김대희 (Claude Code와 함께 작업)

시간 순서대로 무엇을 먼저 시도했고, 무엇이 잘못됐고, 어떻게 고쳤는지 적는다.

## 요약

| # | 한 일 | 결과 |
|---|---|---|
| 1 | 저장소 `dev` 브랜치 pull | 성공 (`e4fee7c` → `d997332`) |
| 2 | 구현 기준 정하기 (PDF 가이드 vs 저장소) | 저장소 기준으로 결정 |
| 3 | `face-model.ino` 작성 — 모델 단독 실행, 시리얼 출력 | 컴파일 성공 |
| 4 | `web-demo/web-demo.ino` 작성 — Wi-Fi + 웹 화면 시연 | 컴파일 성공 |
| 5 | XIAO ESP32S3에 `web-demo` 업로드 | `CORRUPT HEAP`으로 재부팅 반복 |
| 6 | 원인 분석 → `ei_calloc` 16바이트 정렬로 교체 | 컴파일 성공, **보드에서 재확인 필요** |
| 7 | 수정 확인 중 컴파일 오류 + `secrets.h` 삭제 사고 | 코드 위치 수정, `secrets.h`는 다시 만들어야 함 |

---

## 1. 저장소 최신화

- **한 일:** `Real-Time_Face-Recognition_YouTube-Control-System`에서 `git pull origin dev`.
- **결과:** fast-forward로 문제없이 반영. 새로 들어온 것은 `device/face-detector`의 `.env` → `secrets.h` 생성기(`gen_secrets.py`)와 CI(`.github/workflows/ci.yml`). `services/`는 이미 최신이었다.

## 2. 구현 기준 정하기

- **먼저 본 것:** `Zero-Touch 미디어 제어 시스템 — ESP32 구현 가이드.pdf`
- **문제:** PDF와 저장소가 서로 다른 전제를 쓰고 있었다.

| 항목 | PDF 가이드 | 저장소 (팀 합의) |
|---|---|---|
| 얼굴 감지 | esp-dl (보드 내장 모델) | Edge Impulse FOMO (내가 만든 모델) |
| esp32 코어 | 2.0.17 | 3.3.12 |
| broker | broker.hivemq.com (공개) | PC의 Mosquitto (`<PC IP>:1883`) |
| 토픽·메시지 | `zerotouch/<id>/face`, `detected` 문자열 | `zt/<id>/face`, JSON (`docs/contracts/README.md`) |

- **결정:** 다른 파트(face-detector, playback-decider, player)가 이미 저장소 기준으로 만들어져 있으므로 **저장소 기준**을 따랐다.
- **역할 범위:** 루트 `README.md`에서 face-model은 "모델을 만들고 threshold를 정해 Arduino 라이브러리로 내보내는 것"까지다. Wi-Fi·MQTT는 face-detector(박명수) 담당이므로 내 스케치에는 넣지 않았다.

## 3. `face-model.ino` — 모델 단독 실행

- **모델 정보** (zip의 `model_metadata.h`): FOMO, 입력 96×96 RGB, 클래스 `face` 1개, threshold 0.5, Arduino library 1.0.96.
- **처리 흐름:** 카메라 QVGA(320×240) JPEG → RGB888로 풀기 → 가운데 정사각형으로 잘라 96×96으로 줄이기 → 모델 실행 → `face score count infer_ms`를 시리얼에 출력. Edge Impulse 예제(`examples/esp32/esp32_camera`)의 방식을 그대로 따랐다.
- **XIAO에 맞춘 것:** 카메라 핀은 `CAMERA_MODEL_XIAO_ESP32S3`, OV3660 상하 반전, 얼굴이 보이면 LED(GPIO 21)를 켠다.
- **face-detector에 넘길 것:** `runFaceModel(FaceResult&)`의 결과가 `face` 메시지 필드와 같다. face-detector `loop()`의 TODO 자리에 그대로 넣을 수 있다.
- **확인:** Arduino IDE에 들어 있는 `arduino-cli`로 `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`(코어 3.3.12) 컴파일 성공. 448KB(13%)라 기본 파티션으로 충분하다.
- **한계:** `FACE_THRESHOLD`는 0.5 이상만 의미가 있다. 0.5 아래 박스는 모델이 먼저 버린다.

## 4. `web-demo.ino` — 시연용 웹 화면

- **목적:** broker 없이 보드 하나로 "얼굴 감지가 되는지" 눈으로 보여 주기.
- **구성:** 보드가 Wi-Fi에 붙어 웹서버를 띄운다.
  - `/` — 화면. 카메라 사진 위에 얼굴 박스·점수, "얼굴 있음/없음", infer_ms, fps 표시
  - `/frame` — 마지막 JPEG. 그 프레임의 감지 결과를 `X-Result` 헤더(JSON)에 같이 실어서 사진과 박스가 어긋나지 않는다
  - mDNS로 `http://face-model.local/`도 열린다
- **Wi-Fi 설정:** `web-demo/secrets.example.h`를 `secrets.h`로 **복사**해서 채운다 (`.gitignore`의 `device/**/secrets.h`에 걸려 커밋되지 않음).
- **확인:** 컴파일 성공 (1.09MB, 32%).

## 5. 보드에 올렸더니 — `CORRUPT HEAP` 재부팅

업로드, Wi-Fi 연결, 웹서버 시작까지는 정상이었다. 첫 프레임에서 모델을 돌리는 순간 멈추고 재부팅을 반복했다.

```
[wifi] 192.168.0.17
[web] 브라우저에서 http://192.168.0.17/ 또는 http://face-model.local/
CORRUPT HEAP: Bad head at 0x3c1bcfe0. Expected 0xabba1234 got 0x00010000
assert failed: multi_heap_free multi_heap_poisoning.c:279 (head != NULL)
```

## 6. 원인 찾기와 수정

**backtrace 풀기.** 같은 소스로 만든 빌드 파일(`.elf`)에 `xtensa-esp-elf-addr2line`을 돌렸다.

```
free
 ← ei_free                               (edge-impulse-sdk/porting/espressif/ei_classifier_porting.cpp)
 ← tflite_learn_1152864_19_reset         (모델이 쓴 임시 버퍼를 해제하는 곳)
 ← run_nn_inference_image_quantized
 ← run_classifier
 ← runOnce                               (web-demo.ino)
```

→ 내 코드가 아니라 **모델 실행 중에 라이브러리 안에서** 임시 버퍼 앞 메모리가 덮어써졌고, 해제할 때 그게 들켰다.

**원인.**
- ESP32-S3에서는 Edge Impulse가 Espressif의 가속 코드(ESP-NN)를 자동으로 켠다 (`ei_classifier_config.h`).
- ESP-NN은 임시 버퍼가 **16바이트 정렬**이라고 가정한다.
- 라이브러리의 `ei_calloc`은 ESP-IDF 4(코어 2.x)에서는 `aligned_alloc(16, …)`으로 정렬해 할당하지만, **ESP-IDF 5(코어 3.x)에서는 `heap_caps_calloc`으로 정렬 없이** 할당한다.
- 팀 표준이 코어 3.3.12라서 정렬되지 않은 버퍼가 넘어갔고, 그 결과 버퍼 밖을 덮어썼다.

**수정.** 라이브러리 파일은 고치지 않았다. `ei_calloc`은 weak 함수라 스케치에서 같은 이름으로 다시 정의하면 그쪽이 쓰인다.

```cpp
void* ei_calloc(size_t nitems, size_t size) {
  return heap_caps_aligned_calloc(16, nitems, size, MALLOC_CAP_DEFAULT);
}
```

`face-model.ino`도 같은 경로로 모델을 돌리므로 두 스케치에 다 넣었다.

## 7. 수정 확인 중 생긴 문제 두 가지

**(1) 컴파일 오류 — `'FaceResult' was not declared in this scope`**
- **원인:** Arduino IDE는 `.ino`의 첫 함수 정의 바로 앞에 모든 함수 선언을 자동으로 끼워 넣는다. `ei_calloc`을 `struct FaceResult`보다 위에 두니, `runOnce(FaceResult&)` 선언이 구조체보다 앞에 들어가 깨졌다.
- **수정:** `ei_calloc`을 `struct FaceResult` 아래로 옮겼다.
- **확인:** 두 스케치 모두 컴파일 성공. 완성된 펌웨어를 objdump로 열어 `ei_calloc`이 하나뿐이고 `heap_caps_aligned_calloc`을 부르는 것(= 내 함수가 쓰이는 것)까지 확인했다.

**(2) `web-demo/secrets.h` 삭제 사고**
- **무슨 일:** 컴파일 확인을 위해 스케치 폴더에서 "`secrets.example.h` → `secrets.h` 복사 → 컴파일 → `secrets.h` 삭제"를 한 명령으로 돌렸다. 그사이 `secrets.example.h`를 `secrets.h`로 이름을 바꿔 Wi-Fi 정보를 넣어 두었는데, 복사가 실패한 상태에서도 삭제는 그대로 실행돼 **실제 `secrets.h`가 지워졌다**. git에 없는 파일이라 복구할 수 없다.
- **조치:** `secrets.example.h`를 다시 만들었다. 이후 컴파일 확인은 scratchpad의 복사본에서만 하고, 작업 폴더 파일은 건드리지 않는다.
- **내가 할 일:** `cp secrets.example.h secrets.h` 후 Wi-Fi 정보를 다시 넣는다.

## 다음 할 일

- [ ] `web-demo/secrets.h` 다시 만들기
- [ ] `web-demo.ino` 다시 업로드 → `CORRUPT HEAP` 없이 `face=… score=…`가 계속 나오는지 확인
- [ ] 그래도 깨지면: 라이브러리의 `ei_classifier_config.h`에서 `EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN`을 0으로 (ESP-NN 끄기, 느려지지만 확실)
- [ ] `README.md`의 "face-detector에 넘기는 것" 표와 "확인 기록" 표 채우기
- [ ] face-detector(박명수)와 `runFaceModel()` + `ei_calloc` 수정을 넘기는 방법 정하기
- [ ] 브랜치 `feature/face-model/esp32-inference`로 커밋 → `dev`에 PR
