"""recorder 몸체: broker에 붙어 zt/#·$SYS를 받고, 0.5초마다 요약·ping을 돌리고, /health를 연다."""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

from . import config
from .log_config import log_env
from .recorder import Recorder
from .timeline import Timeline

log = logging.getLogger("zt.recorder.main")

SUBSCRIPTIONS = [
    ("zt/#", 1),                                   # control, face, status, playback, log, ping, pong 전부
    ("$SYS/broker/log/#", 0),                      # mosquitto 로그 (mosquitto.conf의 log_dest topic)
    ("$SYS/broker/clients/connected", 0),          # broker 통계 (mosquitto 기본값으로 10초마다)
    ("$SYS/broker/load/messages/+/1min", 0),
    ("$SYS/broker/bytes/+", 0),
    ("$SYS/broker/uptime", 0),
]
TICK_SEC = 0.5


def serve_health(state: dict, recorder: Recorder) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/health", "/stats"):
                self.send_error(404)
                return
            body = {"ok": True, "service": config.SERVICE_NAME, "mqtt": state["connected"]}
            if self.path == "/stats":
                body.update(recorder.stats, devices=sorted(recorder.ping_due), log=str(recorder.timeline.path))
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):   # 헬스체크 요청 로그가 다른 로그를 묻지 않게
            pass

    server = ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def run() -> None:
    env = log_env()
    timeline = Timeline(config.LOG_DIR, config.LOG_MAX_MB, config.LOG_BACKUPS,
                        level=logging.DEBUG if env == "dev" else logging.INFO)
    timeline.attach("zt")   # recorder 자신의 로그도 같은 타임라인에

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.SERVICE_NAME)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    state = {"connected": False}
    recorder = Recorder(
        timeline, publish=lambda t, p: client.publish(t, p, qos=0),
        face_every_s=config.FACE_SUMMARY_S, ping_every_s=config.PING_EVERY_S, pong_wait_s=config.PONG_WAIT_S,
        sys_every_s=config.SYS_SUMMARY_S, face_max_per_s=config.FACE_MAX_PER_S,
    )

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("broker 연결 실패 host=%s rc=%s", config.BROKER_HOST, reason_code)
            return
        state["connected"] = True
        client.subscribe(SUBSCRIPTIONS)
        log.info("broker 연결 host=%s port=%s", config.BROKER_HOST, config.BROKER_PORT)

    def on_disconnect(client, userdata, flags, reason_code, properties):
        state["connected"] = False
        log.warning("broker 끊김 rc=%s (다시 연결한다)", reason_code)

    def on_message(client, userdata, m):
        try:
            recorder.on_message(m.topic, m.payload, m.retain, m.qos)
        except Exception:
            log.exception("메시지 처리 중 예외 topic=%s", m.topic)

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    serve_health(state, recorder)
    log.info("recorder 시작 log_env=%s dir=%s face_every_s=%g ping_every_s=%g sys_every_s=%g",
             env, config.LOG_DIR, config.FACE_SUMMARY_S, config.PING_EVERY_S, config.SYS_SUMMARY_S)
    client.connect_async(config.BROKER_HOST, config.BROKER_PORT, keepalive=30)
    client.loop_start()   # 첫 연결이 실패해도 계속 다시 시도한다
    while True:
        time.sleep(TICK_SEC)
        try:
            recorder.tick()
        except Exception:
            log.exception("주기 작업 중 예외")
