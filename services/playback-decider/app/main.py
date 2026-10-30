"""zt/+/face를 받아 Decider에 넣고, 명령이 나오면 zt/<기기>/playback으로 보낸다.
face가 끊겨도 pause가 나가도록 tick_loop가 0.1초마다 Decider.tick()을 부른다."""

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
from fastapi import FastAPI

from . import config
from .decider import Decider

log = logging.getLogger(config.SERVICE_NAME)

deciders: dict[str, Decider] = {}
stats = {"face_msgs": 0, "bad_msgs": 0, "playback_sent": 0}
# on_message(MQTT 스레드)와 tick_loop(이벤트 루프)가 deciders를 함께 건드린다
lock = threading.Lock()
TICK_SEC = 0.1

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.SERVICE_NAME)


def now_ms() -> int:
    return int(time.monotonic() * 1000)


def send(device: str, action: str | None) -> None:
    if action:
        client.publish(f"zt/{device}/playback", json.dumps({"action": action}), qos=1)
        stats["playback_sent"] += 1


def on_connect(client, userdata, flags, reason_code, properties):
    log.info("broker 연결: %s", reason_code)
    client.subscribe([("zt/+/face", 0), ("zt/+/control", 1)])


def on_message(client, userdata, msg):
    _, device, kind = msg.topic.split("/", 2)
    try:
        data = json.loads(msg.payload)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        stats["bad_msgs"] += 1
        return

    if kind == "control":
        cmd = data.get("cmd")
        if cmd not in ("start", "stop"):
            stats["bad_msgs"] += 1
            return
        with lock:
            deciders.setdefault(device, Decider()).reset(running=cmd == "start", now_ms=now_ms())
        return

    try:
        face, score = bool(data["face"]), float(data.get("score", 0))
    except (KeyError, TypeError, ValueError):
        stats["bad_msgs"] += 1
        return
    stats["face_msgs"] += 1

    with lock:
        action = deciders.setdefault(device, Decider()).update(face, score, now_ms())
    send(device, action)


async def tick_loop():
    """face 메시지가 끊겨도 pause가 나가도록 주기적으로 Decider.tick()을 부른다."""
    while True:
        with lock:
            actions = [(device, d.tick(now_ms())) for device, d in deciders.items()]
        for device, action in actions:
            send(device, action)
        await asyncio.sleep(TICK_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client.on_connect = on_connect
    client.on_message = on_message
    # broker가 아직 없어도 막히지 않고 뒤에서 다시 붙는다
    client.connect_async(config.BROKER_HOST, config.BROKER_PORT)
    client.loop_start()
    ticker = asyncio.create_task(tick_loop())
    yield
    ticker.cancel()
    client.loop_stop()
    client.disconnect()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True, "service": config.SERVICE_NAME, "mqtt": client.is_connected()}


@app.get("/stats")
def get_stats():
    return {
        **stats,
        "devices": {d: dec.last_action for d, dec in deciders.items()},
        "config": {
            "play_after_ms": config.PLAY_AFTER_MS,
            "pause_after_ms": config.PAUSE_AFTER_MS,
            "min_score": config.MIN_SCORE,
        },
    }
