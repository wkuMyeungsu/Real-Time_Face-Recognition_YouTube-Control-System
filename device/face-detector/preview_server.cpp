// 카메라 미리보기 웹 서버 (esp_http_server, 자체 태스크에서 돈다).
//   GET /           미리보기 페이지. /frame.jpg를 계속 받아 캔버스에 그린다
//   GET /frame.jpg  최근 장 JPEG. 헤더 X-Crop [x,y,한 변], X-Boxes [[x,y,w,h,score],...], X-Inferred 1|0
// 핸들러는 웹 서버 태스크에서 돌므로 LOG*를 쓰지 않는다 (log sink가 MQTT로 보내는데 PubSubClient는 loop 태스크 전용).
#include <WiFi.h>
#include <ESPmDNS.h>
#include <esp_http_server.h>
#include "secrets.h"  // DEVICE_ID
#include "face_runner.h"
#include "preview_server.h"
#include "log.h"

#define PREVIEW_PORT 80
#define FRAME_BUF_CAP (64 * 1024)

static uint8_t* frameBuf = nullptr;

static const char PAGE[] = R"HTML(<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>face-detector 미리보기</title>
<style>
body{margin:0;background:#111;color:#eee;font:14px sans-serif;display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px}
canvas{width:min(100%,640px);image-rendering:pixelated;background:#000}
label{user-select:none}
</style></head><body>
<canvas id="c" width="320" height="240"></canvas>
<div id="s">연결 중…</div>
<label><input type="checkbox" id="m"> 거울처럼 좌우 반전</label>
<script>
const c=document.getElementById('c'),g=c.getContext('2d'),s=document.getElementById('s'),m=document.getElementById('m');
async function tick(){
  try{
    const r=await fetch('/frame.jpg',{cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);
    const crop=JSON.parse(r.headers.get('X-Crop')),boxes=JSON.parse(r.headers.get('X-Boxes'));
    const inferred=r.headers.get('X-Inferred')==='1';
    const img=await createImageBitmap(await r.blob());
    g.setTransform(m.checked?-1:1,0,0,1,m.checked?c.width:0,0);
    g.drawImage(img,0,0);
    g.lineWidth=1;g.strokeStyle='#ffd400';g.setLineDash([4,3]);
    g.strokeRect(crop[0]+.5,crop[1]+.5,crop[2]-1,crop[2]-1);
    g.setLineDash([]);g.lineWidth=2;g.strokeStyle='#00e676';
    for(const b of boxes)g.strokeRect(b[0],b[1],b[2],b[3]);
    g.setTransform(1,0,0,1,0,0);
    g.font='12px sans-serif';g.fillStyle='#00e676';
    for(const b of boxes){const x=m.checked?c.width-b[0]-b[2]:b[0];g.fillText(b[4].toFixed(2),x+2,b[1]>14?b[1]-3:b[1]+b[3]+12);}
    s.textContent=inferred?`감지 중 · 얼굴 ${boxes.length}개 (노란 점선 안만 모델이 본다)`
                          :'감지 꺼짐 · control start를 보내면 얼굴 박스가 그려진다';
  }catch(e){
    s.textContent='연결 끊김: '+e.message;
    await new Promise(r=>setTimeout(r,1000));
  }
  setTimeout(tick,100);
}
tick();
</script></body></html>)HTML";

static esp_err_t handlePage(httpd_req_t* req) {
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  return httpd_resp_send(req, PAGE, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t handleFrame(httpd_req_t* req) {
  PreviewFrame f;
  if (!faceModelPreview(frameBuf, FRAME_BUF_CAP, f)) {
    httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no frame");
    return ESP_FAIL;
  }

  int cropX, cropY, cropSide;
  faceModelCropRect(cropX, cropY, cropSide);
  char crop[32];
  snprintf(crop, sizeof crop, "[%d,%d,%d]", cropX, cropY, cropSide);

  char boxes[PREVIEW_MAX_BOXES * 40 + 4];
  size_t n = snprintf(boxes, sizeof boxes, "[");
  for (uint8_t i = 0; i < f.boxCount; i++) {
    const FaceBox& b = f.boxes[i];
    n += snprintf(boxes + n, sizeof boxes - n, "%s[%d,%d,%d,%d,%.2f]",
                  i ? "," : "", b.x, b.y, b.w, b.h, b.score);
  }
  snprintf(boxes + n, sizeof boxes - n, "]");

  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  httpd_resp_set_hdr(req, "X-Crop", crop);
  httpd_resp_set_hdr(req, "X-Boxes", boxes);
  httpd_resp_set_hdr(req, "X-Inferred", f.inferred ? "1" : "0");
  return httpd_resp_send(req, (const char*)frameBuf, f.jpegLen);
}

bool startPreviewServer() {
  frameBuf = (uint8_t*)ps_malloc(FRAME_BUF_CAP);
  if (!frameBuf) {
    LOGE("camera", "미리보기 버퍼 할당 실패 need_kb=%d", FRAME_BUF_CAP / 1024);
    return false;
  }
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = PREVIEW_PORT;
  httpd_handle_t server = nullptr;
  esp_err_t err = httpd_start(&server, &config);
  if (err != ESP_OK) {
    LOGE("camera", "미리보기 서버 시작 실패 err=0x%x", (unsigned)err);
    return false;
  }
  httpd_uri_t page = {"/", HTTP_GET, handlePage, nullptr};
  httpd_uri_t frame = {"/frame.jpg", HTTP_GET, handleFrame, nullptr};
  httpd_register_uri_handler(server, &page);
  httpd_register_uri_handler(server, &frame);
  // IP는 공유기가 정하므로 DEVICE_ID.local 이름으로도 열 수 있게 한다 (mDNS)
  if (MDNS.begin(DEVICE_ID)) MDNS.addService("http", "tcp", PREVIEW_PORT);
  else LOGW("camera", "mDNS 시작 실패, IP로 연다 host=%s", DEVICE_ID);
  LOGI("camera", "미리보기 켜짐 url=http://%s/ url_ip=http://%s/", DEVICE_ID ".local", WiFi.localIP().toString().c_str());
  return true;
}
