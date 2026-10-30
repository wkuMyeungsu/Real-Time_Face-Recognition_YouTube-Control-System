"""루트 tests/ 공용 도우미: 환경값, MQTT 탐침, 가짜 face-detector, 가짜 유튜브 플레이어, 계약 스키마."""
from __future__ import annotations

import json
import os
import queue
import random
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "docs" / "contracts"
DEVICE_TOPICS = ("control", "face", "status", "playback")   # 서비스가 주고받는 토픽
TOPICS = DEVICE_TOPICS + ("log", "ping", "pong")            # 계약 문서의 모든 토픽 (log·ping·pong은 디버깅용)
LOGS = ROOT / "logs"                                         # recorder가 쓰는 곳 (docker-compose.yml의 ./logs)


def read_env(path: Path) -> dict:
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.split("#", 1)[0].strip()
    return values


def settings() -> dict:
    """기준값: .env가 있으면 .env, 없으면 .env.example (CI는 .env.example을 복사해 쓴다)."""
    v = read_env(ROOT / ".env.example")
    v.update(read_env(ROOT / ".env"))
    v.update({k: os.environ[k] for k in ("MQTT_PORT", "PLAYER_PORT", "PLAYBACK_DECIDER_PORT", "RECORDER_PORT", "PLAY_AFTER_MS", "PAUSE_AFTER_MS", "MIN_SCORE") if k in os.environ})
    return {
        "host": os.environ.get("ZT_TEST_HOST", "localhost"),
        "mqtt_port": int(v.get("MQTT_PORT", 1883)),
        "player_port": int(v.get("PLAYER_PORT", 8080)),
        "decider_port": int(v.get("PLAYBACK_DECIDER_PORT", 8001)),
        "recorder_port": int(v.get("RECORDER_PORT", 8002)),
        "play_ms": int(v.get("PLAY_AFTER_MS", 500)),
        "pause_ms": int(v.get("PAUSE_AFTER_MS", 1500)),
        "min_score": float(v.get("MIN_SCORE", 0.6)),
    }


def schema(kind: str) -> dict:
    return json.loads((CONTRACTS / "schemas" / f"{kind}.schema.json").read_text(encoding="utf-8"))


def validate(kind: str, payload) -> None:
    import jsonschema

    jsonschema.validate(payload, schema(kind), cls=jsonschema.Draft202012Validator)


def topic(device: str, kind: str) -> str:
    return f"zt/{device}/{kind}"


def unique_device(prefix: str) -> str:
    """테스트마다 다른 기기. playback-decider는 zt/+/…로 모든 기기를 받으므로 섞이지 않는다."""
    return f"t-{prefix}-{random.randint(10000, 99999)}"


def http_json(url: str, timeout: float = 5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body or b"null")
            except ValueError:
                return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None


class Probe:
    """구독한 메시지를 큐로 받는 MQTT 클라이언트."""

    def __init__(self, host, port, name="probe", transport="tcp", ws_path="/mqtt", will=None, keepalive=10):
        self.messages: queue.Queue = queue.Queue()
        self.connected = threading.Event()
        self.failed = None
        cid = f"test-{name}-{os.getpid()}-{random.randint(1000, 9999)}"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, transport=transport)
        if transport == "websockets":
            self.client.ws_set_options(path=ws_path)
        if will:
            self.client.will_set(*will)
        self.client.on_connect = self._on_connect
        self.client.on_message = lambda c, u, m: self.messages.put((time.monotonic(), m.topic, m.payload, m.retain, m.qos))
        self.host, self.port, self.keepalive = host, port, keepalive

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.failed = str(reason_code)
        self.connected.set()

    def start(self, timeout=5) -> bool:
        try:
            self.client.connect(self.host, self.port, keepalive=self.keepalive)
        except OSError as e:
            self.failed = f"{e.__class__.__name__}: {e}"
            return False
        self.client.loop_start()
        return self.connected.wait(timeout) and self.failed is None

    def subscribe(self, pattern, qos=1):
        self.client.subscribe(pattern, qos=qos)
        time.sleep(0.3)  # SUBACK 기다림

    def next(self, want_topic, check=lambda p: True, timeout=5.0):
        """(받은 시각, JSON, retain, qos) 또는 None."""
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                at, t, payload, retained, qos = self.messages.get(timeout=left)
            except queue.Empty:
                return None
            if t != want_topic or not payload:
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if check(data):
                return at, data, retained, qos
        return None

    def expect(self, want_topic, check=lambda p: True, timeout=5.0):
        got = self.next(want_topic, check, timeout)
        return got[1] if got else None

    def drain(self):
        while not self.messages.empty():
            self.messages.get_nowait()

    def publish(self, t, payload, retain=False, qos=1):
        data = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        self.client.publish(t, data, qos=qos, retain=retain).wait_for_publish(timeout=3)

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()


class LogTail:
    """recorder가 logs/에 새로 붙이는 줄만 읽는다. 만든 순간 이후의 줄만 본다 (파일이 돌려지면 처음부터)."""

    def __init__(self, name: str = "zt.log"):
        self.path = LOGS / name
        self.offset = self.path.stat().st_size if self.path.exists() else 0

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        if self.path.stat().st_size < self.offset:
            self.offset = 0
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            return f.read().decode("utf-8", "replace").splitlines()

    def wait(self, check, timeout: float = 5.0):
        end = time.monotonic() + timeout
        while True:
            for line in self.lines():
                if check(line):
                    return line
            if time.monotonic() > end:
                return None
            time.sleep(0.1)


class FaceFeeder:
    """face-detector 흉내: docs/contracts의 face 형식으로 초당 10개를 보낸다. present·score를 바꿔 가며 쓴다."""

    def __init__(self, probe: Probe, device: str, hz: float = 10):
        self.probe, self.device, self.interval = probe, device, 1 / hz
        self.present, self.score, self.paused, self.seq = False, 0.9, False, 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def message(self) -> dict:
        score = self.score if self.present else 0.0
        return {"seq": self.seq, "face": self.present, "score": round(score, 2), "count": 1 if self.present else 0,
                "infer_ms": random.randint(80, 110)}

    def _run(self):
        t = topic(self.device, "face")
        while not self._stop.is_set():
            if not self.paused:
                self.probe.client.publish(t, json.dumps(self.message()), qos=0)
                self.seq += 1
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=1)


# https://www.youtube.com/iframe_api 대신 넣는 가짜 플레이어. 호출을 window.__yt에 기록한다.
FAKE_YOUTUBE_API = """
(() => {
  window.__yt = [];
  class Player {
    constructor(el, opts) {
      this.opts = opts || {}; this.state = -1;
      window.__yt.push(["new", typeof el === "string" ? el : (el && el.id) || null]);
      setTimeout(() => this.opts.events && this.opts.events.onReady && this.opts.events.onReady({ target: this }), 50);
    }
    playVideo() { this.state = 1; window.__yt.push(["playVideo"]); this._change(); }
    pauseVideo() { this.state = 2; window.__yt.push(["pauseVideo"]); this._change(); }
    stopVideo() { this.state = 0; window.__yt.push(["stopVideo"]); }
    loadVideoById(a) { window.__yt.push(["loadVideoById", typeof a === "object" ? a.videoId : a]); }
    cueVideoById(a) { window.__yt.push(["cueVideoById", typeof a === "object" ? a.videoId : a]); }
    getPlayerState() { return this.state; }
    _change() { const f = this.opts.events && this.opts.events.onStateChange; if (f) f({ target: this, data: this.state }); }
  }
  window.YT = { Player, PlayerState: { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 }, loaded: 1 };
  setTimeout(() => window.onYouTubeIframeAPIReady && window.onYouTubeIframeAPIReady(), 0);
})();
"""


def open_player(browser, cfg, device):
    """player 페이지를 연다. 유튜브는 가짜로, mqtt.js는 ZT_MQTT_JS(로컬 파일)가 있으면 그것으로 바꾼다 (CDN이 막힌 곳용)."""
    context = browser.new_context()
    context.route("https://www.youtube.com/**", lambda r: r.abort())  # 나중에 등록한 route를 먼저 본다
    context.route("https://www.youtube.com/iframe_api*", lambda r: r.fulfill(status=200, content_type="text/javascript", body=FAKE_YOUTUBE_API))
    local_mqtt = os.environ.get("ZT_MQTT_JS")
    if local_mqtt:
        context.route("**/mqtt.min.js", lambda r: r.fulfill(status=200, content_type="text/javascript", path=local_mqtt))
    page = context.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(f"http://{cfg['host']}:{cfg['player_port']}/?device={device}")
    return context, page


def clear_retained(cfg, device):
    probe = Probe(cfg["host"], cfg["mqtt_port"], "clean")
    if probe.start():
        for kind in DEVICE_TOPICS:
            probe.publish(topic(device, kind), b"", retain=True)
        probe.stop()
