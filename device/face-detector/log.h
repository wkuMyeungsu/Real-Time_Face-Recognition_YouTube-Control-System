// 시리얼 로그를 팀 공통 형식(수업 Day11 logging 형식)으로 찍는다.
//   [up 12345ms] INFO     zt.face-detector.wifi face-detector.ino:62 연결됨 ip=172.30.1.57 rssi_dbm=-48
// asctime 자리에는 부팅 후 경과 시간(up_ms)을 찍는다. ESP32 시계는 PC와 맞춰져 있지 않다.
// 쓰는 법: LOGI("wifi", "연결됨 ip=%s rssi_dbm=%d", ip, rssi). 메시지는 한국어 한 문장 + key=value, 단위는 키 끝(_ms, _kb, _dbm).
// 비밀번호 같은 비밀값은 찍지 않는다.
#pragma once
#include <Arduino.h>
#include <stdarg.h>

#define ZT_LOG_DEBUG    10
#define ZT_LOG_INFO     20
#define ZT_LOG_WARNING  30
#define ZT_LOG_ERROR    40
#define ZT_LOG_CRITICAL 50

// 이 레벨 이상만 찍는다. 개발 중 자세히 보려면 #include "log.h" 앞에 #define ZT_LOG_LEVEL ZT_LOG_DEBUG
#ifndef ZT_LOG_LEVEL
#define ZT_LOG_LEVEL ZT_LOG_INFO
#endif

inline const char* ztLogLevelName(int level) {
  switch (level) {
    case ZT_LOG_DEBUG:   return "DEBUG";
    case ZT_LOG_INFO:    return "INFO";
    case ZT_LOG_WARNING: return "WARNING";
    case ZT_LOG_ERROR:   return "ERROR";
    default:             return "CRITICAL";
  }
}

inline const char* ztLogBaseName(const char* path) {
  const char* base = path;
  for (const char* p = path; *p; p++) {
    if (*p == '/' || *p == '\\') base = p + 1;
  }
  return base;
}

// INFO 이상 로그를 시리얼 말고도 보낼 곳 (MQTT log 토픽). 스케치가 ztSetLogSink()로 건다. DEBUG는 보내지 않는다.
typedef void (*ZtLogSink)(int level, const char* module, const char* file, int line, const char* msg);

inline ZtLogSink& ztLogSinkRef() {
  static ZtLogSink sink = nullptr;
  return sink;
}

inline void ztSetLogSink(ZtLogSink sink) { ztLogSinkRef() = sink; }

inline void ztLog(int level, const char* module, const char* file, int line, const char* fmt, ...) {
  if (level < ZT_LOG_LEVEL) return;
  char msg[192];
  va_list args;
  va_start(args, fmt);
  vsnprintf(msg, sizeof msg, fmt, args);
  va_end(args);
  Serial.printf("[up %lums] %-8s zt.face-detector.%s %s:%d %s\n",
                millis(), ztLogLevelName(level), module, ztLogBaseName(file), line, msg);
  if (level >= ZT_LOG_INFO && ztLogSinkRef()) ztLogSinkRef()(level, module, ztLogBaseName(file), line, msg);
}

// module: 로거 이름의 마지막 칸 (boot, wifi, mqtt, camera, infer)
#define LOGD(module, ...) ztLog(ZT_LOG_DEBUG, module, __FILE__, __LINE__, __VA_ARGS__)
#define LOGI(module, ...) ztLog(ZT_LOG_INFO, module, __FILE__, __LINE__, __VA_ARGS__)
#define LOGW(module, ...) ztLog(ZT_LOG_WARNING, module, __FILE__, __LINE__, __VA_ARGS__)
#define LOGE(module, ...) ztLog(ZT_LOG_ERROR, module, __FILE__, __LINE__, __VA_ARGS__)
#define LOGC(module, ...) ztLog(ZT_LOG_CRITICAL, module, __FILE__, __LINE__, __VA_ARGS__)
