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
from .mqtt_log import MqttLogHandler, kv

log = logging.getLogger("zt.playback-decider.main")

deciders: dict[str, Decider] = {}
stats = {"face_msgs": 0, "bad_msgs": 0, "playback_sent": 0}
# on_message(MQTT 스레드)와 tick_loop(이벤트 루프)가 deciders를 함께 건드린다
lock = threading.Lock()
TICK_SEC = 0.1
BAD_SUMMARY_SEC = 5

# 기기별 마지막 face seq (건너뜀·재부팅 확인)
last_seqs: dict[str, int] = {}
# 잘못된 메시지는 초당 10개까지 올 수 있어 기기별로 모아 BAD_SUMMARY_SEC마다 한 줄로 남긴다
bad_counts: dict[tuple[str, str], int] = {}

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.SERVICE_NAME)


def now_ms() -> int:
    return int(time.monotonic() * 1000)


def send(device: str, action: str | None) -> None:
    if action:
        client.publish(f"zt/{device}/playback", json.dumps({"action": action}), qos=1)
        stats["playback_sent"] += 1


def decider_for(device: str) -> Decider:
    if device not in deciders:
        deciders[device] = Decider(device=device)
    return deciders[device]


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        kv(log, logging.ERROR, "broker 연결 실패", host=config.BROKER_HOST, port=config.BROKER_PORT, rc=str(reason_code))
        return
    kv(log, logging.INFO, "broker 연결됨", host=config.BROKER_HOST, port=config.BROKER_PORT)
    client.subscribe([("zt/+/face", 0), ("zt/+/control", 1)])


def on_disconnect(client, userdata, flags, reason_code, properties):
    kv(log, logging.ERROR, "broker 연결 끊김", rc=str(reason_code))


FACE_FIELDS = {"seq", "face", "score", "count", "infer_ms"}


def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def face_error(data: dict) -> str | None:
    """docs/contracts/schemas/face.schema.json과 같은 기준. 맞으면 None, 틀리면 이유("fields"·"type")."""
    if set(data) != FACE_FIELDS:
        return "fields"
    score = data["score"]
    ok = (
        isinstance(data["face"], bool)
        and isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 1
        and _count(data["seq"]) and _count(data["count"]) and _count(data["infer_ms"])
    )
    return None if ok else "type"


def valid_face(data: dict) -> bool:
    return face_error(data) is None


def bad(device: str, kind: str, reason: str) -> None:
    stats["bad_msgs"] += 1
    with lock:
        key = (f"zt/{device}/{kind}", reason)
        bad_counts[key] = bad_counts.get(key, 0) + 1


def flush_bad() -> None:
    """모아 둔 잘못된 메시지를 토픽·이유별로 한 줄씩 남긴다."""
    with lock:
        counts = dict(bad_counts)
        bad_counts.clear()
    for (topic, reason), count in counts.items():
        kv(log, logging.WARNING, "잘못된 메시지", device=topic.split("/")[1],
           topic=topic, reason=reason, count=count, window_s=BAD_SUMMARY_SEC)


def check_seq(device: str, seq: int) -> None:
    prev = last_seqs.get(device)
    last_seqs[device] = seq
    if prev is None or seq == prev + 1:
        return
    if seq <= prev:
        # face-detector는 부팅할 때 seq를 0부터 다시 센다
        kv(log, logging.WARNING, "seq가 줄어듦, ESP32 재부팅 추정", device=device, prev=prev, got=seq)
    else:
        kv(log, logging.WARNING, "seq 건너뜀", device=device, expected=prev + 1, got=seq, lost=seq - prev - 1)


def on_message(client, userdata, msg):
    try:
        handle(msg.topic, msg.payload)
    except Exception:
        kv(log, logging.ERROR, "메시지 처리 중 예외", topic=msg.topic, exc_info=True)


def handle(topic: str, payload: bytes) -> None:
    _, device, kind = topic.split("/", 2)
    try:
        data = json.loads(payload)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        bad(device, kind, "json")
        return

    if kind == "control":
        cmd = data.get("cmd")
        if cmd not in ("start", "stop"):
            bad(device, kind, "cmd")
            return
        kv(log, logging.INFO, "control 받음, 판정 초기화", device=device, cmd=cmd)
        with lock:
            decider_for(device).reset(running=cmd == "start", now_ms=now_ms())
        return

    error = face_error(data)
    if error:
        bad(device, kind, error)
        return
    face, score, seq = data["face"], float(data["score"]), data["seq"]
    stats["face_msgs"] += 1
    log.debug("face device=%s seq=%d face=%s score=%.2f infer_ms=%d", device, seq, face, score, data["infer_ms"])

    with lock:
        check_seq(device, seq)
        action = decider_for(device).update(face, score, now_ms(), seq)
    send(device, action)


async def tick_loop():
    """face 메시지가 끊겨도 pause가 나가도록 주기적으로 Decider.tick()을 부른다."""
    next_flush = time.monotonic() + BAD_SUMMARY_SEC
    while True:
        with lock:
            actions = [(device, d.tick(now_ms())) for device, d in deciders.items()]
        for device, action in actions:
            send(device, action)
        if time.monotonic() >= next_flush:
            flush_bad()
            next_flush += BAD_SUMMARY_SEC
        await asyncio.sleep(TICK_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    kv(log, logging.INFO, "시작", play_after_ms=config.PLAY_AFTER_MS, pause_after_ms=config.PAUSE_AFTER_MS,
       min_score=config.MIN_SCORE, broker=f"{config.BROKER_HOST}:{config.BROKER_PORT}")
    # INFO 이상은 log 토픽으로도 보낸다 (docs/contracts의 log). 콘솔 핸들러는 공통 설정(zt 로거)에 있다
    mqtt_log = MqttLogHandler(client)
    logging.getLogger("zt.playback-decider").addHandler(mqtt_log)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    # broker가 아직 없어도 막히지 않고 뒤에서 다시 붙는다
    client.connect_async(config.BROKER_HOST, config.BROKER_PORT)
    client.loop_start()
    ticker = asyncio.create_task(tick_loop())
    yield
    ticker.cancel()
    logging.getLogger("zt.playback-decider").removeHandler(mqtt_log)
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
