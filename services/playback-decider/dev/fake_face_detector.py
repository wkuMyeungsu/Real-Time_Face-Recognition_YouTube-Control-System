"""보드 없이 face-detector(ESP32) 흉내를 낸다. docs/contracts/README.md 형식대로 status·face를 보낸다.

  docker compose exec -it playback-decider python dev/fake_face_detector.py   # 컨테이너 안 (broker로 접속)
  python dev/fake_face_detector.py --host localhost                            # PC에서 (pip install paho-mqtt)

player에서 시작 버튼을 누르면({"cmd":"start"}) 보내기 시작한다. --running이면 바로 보낸다.
Enter를 칠 때마다 얼굴 있음/없음이 바뀐다. q + Enter로 끝낸다.
"""

import argparse
import json
import os
import random
import threading
import time

import paho.mqtt.client as mqtt

parser = argparse.ArgumentParser()
parser.add_argument("--host", default=os.environ.get("BROKER_HOST", "localhost"))
parser.add_argument("--port", type=int, default=1883)
parser.add_argument("--device", default="esp32-a")
parser.add_argument("--hz", type=float, default=5)
parser.add_argument("--running", action="store_true")
args = parser.parse_args()

base = f"zt/{args.device}"
state = {"running": args.running, "face": True, "seq": 0}

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-{args.device}")
client.will_set(f"{base}/status", json.dumps({"state": "offline"}), qos=1, retain=True)


def publish_status():
    s = "running" if state["running"] else "idle"
    client.publish(f"{base}/status", json.dumps({"state": s, "fw": "fake"}), qos=1, retain=True)


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(f"{base}/control", qos=1)
    publish_status()


def on_message(client, userdata, msg):
    try:
        cmd = json.loads(msg.payload).get("cmd")
    except (ValueError, AttributeError):
        return
    if cmd in ("start", "stop"):
        state["running"] = cmd == "start"
        publish_status()
        print(f"[control] {cmd}")


def send_loop():
    while True:
        if state["running"]:
            face = state["face"]
            msg = {
                "seq": state["seq"],
                "face": face,
                "score": round(random.uniform(0.75, 0.95) if face else random.uniform(0.0, 0.3), 2),
                "count": 1 if face else 0,
                "infer_ms": random.randint(80, 120),
            }
            client.publish(f"{base}/face", json.dumps(msg))
            state["seq"] += 1
        time.sleep(1 / args.hz)


client.on_connect = on_connect
client.on_message = on_message
client.connect(args.host, args.port)
client.loop_start()
threading.Thread(target=send_loop, daemon=True).start()

print(f"{args.host}:{args.port} {base} — Enter: 얼굴 있음/없음 바꾸기, q: 끝")
while input().strip() != "q":
    state["face"] = not state["face"]
    print("얼굴 있음" if state["face"] else "얼굴 없음")

client.publish(f"{base}/status", json.dumps({"state": "offline"}), qos=1, retain=True).wait_for_publish()
client.loop_stop()
client.disconnect()
