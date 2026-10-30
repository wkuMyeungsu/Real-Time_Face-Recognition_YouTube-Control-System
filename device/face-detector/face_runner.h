// 카메라 한 장 → face-model(Edge Impulse FOMO) 실행. device/face-model/face-model.ino(김대희)의 방식을 그대로 가져왔다.
// 모델 라이브러리는 device/face-model/*.zip (python setup_arduino.py가 설치한다).
#pragma once
#include <Arduino.h>

// docs/contracts/README.md의 face 메시지 필드와 같다 (captureMs는 로그용)
struct FaceResult {
  bool face;           // FACE_THRESHOLD를 넘은 얼굴이 하나라도 있으면 true
  float score;         // 가장 높은 얼굴 점수 (없으면 0)
  int count;           // FACE_THRESHOLD를 넘은 얼굴 수
  uint32_t inferMs;    // 전처리(DSP) + 모델 실행 시간
  uint32_t captureMs;  // 촬영 + JPEG 풀기 + 96×96으로 줄이기
};

// PSRAM 버퍼와 카메라를 준비한다. 실패하면 CRITICAL 로그를 남기고 false
bool faceModelBegin();

// 한 장 찍어 모델을 돌린다. 촬영·모델 실패면 false (로그는 여기서 남긴다)
bool runFaceModel(FaceResult& out);

// 로그에 찍을 모델 버전. 예: ei-1152864-v96 (Edge Impulse 프로젝트 ID, 배포 버전)
const char* faceModelVersion();

// ───────── 미리보기 (preview_server.cpp) ─────────

#define PREVIEW_MAX_BOXES 10

// 얼굴 박스. 좌표는 카메라 원본(320×240) 픽셀
struct FaceBox {
  int16_t x, y, w, h;
  float score;
};

struct PreviewFrame {
  size_t jpegLen;
  bool inferred;      // 모델이 돌린 장이면 true. 감지가 꺼져 있을 때는 미리보기가 직접 찍어 false
  uint8_t boxCount;   // FACE_THRESHOLD를 넘은 박스만
  FaceBox boxes[PREVIEW_MAX_BOXES];
};

// 모델이 보는 영역(가운데 정사각형)을 원본 픽셀로
void faceModelCropRect(int& x, int& y, int& side);

// 마지막으로 모델이 돌린 JPEG를 dst에 복사한다. 감지가 꺼져 있으면 새로 한 장 찍는다. 실패면 false
// 웹 서버 태스크에서 불린다. MQTT로 나가는 로그(LOG*)를 남기지 않는다
bool faceModelPreview(uint8_t* dst, size_t cap, PreviewFrame& out);
