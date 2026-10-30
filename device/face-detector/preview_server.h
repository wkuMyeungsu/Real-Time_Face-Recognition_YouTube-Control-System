// 카메라 미리보기 웹 서버. 같은 Wi-Fi의 브라우저로 http://<보드 IP>/ 를 열면
// 카메라 화면 위에 모델이 보는 영역(노란 점선)과 찾은 얼굴 박스(초록)를 그린다. 얼굴이 화면에 제대로 들어오는지 맞출 때 쓴다.
// MQTT 계약과는 상관없는 디버그 화면이다.
#pragma once
#include <Arduino.h>

// Wi-Fi 연결 뒤 한 번 부른다. 실패하면 ERROR 로그를 남기고 false (감지는 그대로 돈다)
bool startPreviewServer();
