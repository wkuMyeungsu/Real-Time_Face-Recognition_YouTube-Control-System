"""zt/+/face를 받아 Decider에 넣고, 명령이 나오면 zt/<기기>/player로 보낸다."""

import json
import logging
import time
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
from fastapi import FastAPI

from . import config
from .decider import Decider

log = logging.getLogger(config.SERVICE_NAME)

deciders: dict[str, Decider] = {}
stats = {"face_msgs": 0, "bad_msgs": 0, "player_sent": 0}

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.SERVICE_NAME)


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

    decider = deciders.setdefault(device, Decider())
    if kind == "control":
        decider.reset()
        return

    try:
        face, score = bool(data["face"]), float(data.get("score", 0))
    except (KeyError, TypeError, ValueError):
        stats["bad_msgs"] += 1
        return
    stats["face_msgs"] += 1

    action = decider.update(face, score, int(time.monotonic() * 1000))
    if action:
        client.publish(f"zt/{device}/player", json.dumps({"action": action}), qos=1)
        stats["player_sent"] += 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    client.on_connect = on_connect
    client.on_message = on_message
    # broker가 아직 없어도 막히지 않고 뒤에서 다시 붙는다
    client.connect_async(config.BROKER_HOST, config.BROKER_PORT)
    client.loop_start()
    yield
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
