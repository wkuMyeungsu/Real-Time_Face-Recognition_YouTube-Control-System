# face-model — 얼굴 감지 모델

Edge Impulse에서 만든 얼굴 감지 모델과 그 기록. face-detector가 이 폴더의 결과물을 받아 ESP32에서 실행한다.

## 스케치

| 파일 | 하는 일 |
|---|---|
| `face-model.ino` | 모델만 단독 실행. 결과를 시리얼(115200)로 출력 |
| `web-demo/web-demo.ino` | 시연용. Wi-Fi에 붙어 웹서버를 띄우고, 브라우저에 카메라 화면 + 얼굴 박스를 보여 준다 (MQTT 없음) |

공통 준비: 이 폴더의 `ei-face-detection--fomo--bigger-dataset-arduino-1.0.96-….zip`을 Sketch → Include Library → Add .ZIP Library로 설치. Tools → Board XIAO_ESP32S3, PSRAM **OPI PSRAM**.

`web-demo`는 `secrets.example.h`를 같은 폴더에 `secrets.h`로 복사해 Wi-Fi(2.4GHz)를 채운 뒤 업로드한다. 시리얼에 나온 `http://<IP>/`를 같은 Wi-Fi의 PC·휴대폰 브라우저로 연다.

## face-detector에 넘기는 것

| 항목 | 값 |
|---|---|
| Edge Impulse 프로젝트 | (주소) |
| 모델 종류 | FOMO |
| 입력 | 96×96 RGB |
| 클래스 | face |
| threshold | 0.5 |
| 내보낸 형식 | Arduino library (.zip) — 이 폴더의 `ei-face-detection--fomo--bigger-dataset-arduino-1.0.96-….zip` |
| 내보낸 버전·날짜 | 1.0.96 · 2026-10-30 |

## 확인 기록

| 상황 | 기대 | 결과 |
|---|---|---|
| 정면 얼굴 | 감지 | |
| 옆얼굴 (고개 90° 돌림) | 감지 안 됨 | |
| 화면 앞에 사람 없음 | 감지 안 됨 | |
| 두 사람 | 감지 | |
| 어두운 조명 | 감지 | |
