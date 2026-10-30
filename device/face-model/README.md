# face-model — 얼굴 감지 모델

Edge Impulse에서 만든 얼굴 감지 모델과 그 기록. face-detector가 이 폴더의 결과물을 받아 ESP32에서 실행한다.

## face-detector에 넘기는 것

| 항목 | 값 |
|---|---|
| Edge Impulse 프로젝트 | (주소) |
| 모델 종류 | (예: FOMO) |
| 입력 | (예: 96×96 grayscale) |
| 클래스 | (예: face) |
| threshold | |
| 내보낸 형식 | Arduino library (.zip) |
| 내보낸 버전·날짜 | |

## 확인 기록

| 상황 | 기대 | 결과 |
|---|---|---|
| 정면 얼굴 | 감지 | |
| 옆얼굴 (고개 90° 돌림) | 감지 안 됨 | |
| 화면 앞에 사람 없음 | 감지 안 됨 | |
| 두 사람 | 감지 | |
| 어두운 조명 | 감지 | |
