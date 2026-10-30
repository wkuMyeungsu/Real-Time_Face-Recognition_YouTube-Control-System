"""받은 MQTT 메시지를 한 타임라인으로 바꾼다 (docs/logging-design.txt 5·6장).

- log      : 보낸 파트의 레벨·로거·위치 그대로 zt.log에 옮긴다
- face     : 원문은 zt.jsonl에만. zt.log에는 기기마다 5초 요약 (받은 수, seq 건너뜀, 추론 시간)
- ping/pong: 기기마다 ping을 보내 왕복 시간 rtt_ms를 잰다. 두 기기의 시계를 맞출 필요가 없다
- control·status·playback: 받은 내용을 한 줄로. status offline(LWT)은 WARNING
- $SYS     : broker 로그는 zt.broker로 옮기고, 통계는 1분마다 요약

MQTT와 파일에서 떼어 두어 시계(now)와 publish를 바꿔 끼우면 단위 테스트가 된다.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass

LEVELS = {"INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}
BROKER_LEVELS = {"E": logging.ERROR, "W": logging.WARNING, "N": logging.INFO, "I": logging.INFO, "D": logging.DEBUG}
LOGGER_NAME = re.compile(r"^zt\.[a-z0-9-]+(\.[a-z0-9_-]+)*$")
SECRET_KEY = re.compile(r"pass|pwd|token|secret", re.I)
BROKER_TIME = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d|\d+): ")
SYS_KEYS = {
    "clients/connected": "clients",
    "load/messages/received/1min": "msgs_recv_per_min",
    "load/messages/sent/1min": "msgs_sent_per_min",
    "bytes/received": "bytes_recv",
    "bytes/sent": "bytes_sent",
    "uptime": "uptime_s",
}

mqtt_log = logging.getLogger("zt.recorder.mqtt")
face_log = logging.getLogger("zt.recorder.face")
ping_log = logging.getLogger("zt.recorder.ping")
broker_log = logging.getLogger("zt.broker")


def mask(key: str, value):
    """비밀값은 앞 두 글자만 남긴다 (setup_arduino.py와 같은 방식)."""
    if isinstance(value, str) and SECRET_KEY.search(key):
        return value[:2] + "***"
    return value


def kv(fields: dict) -> str:
    """{"a": 1, "b": "x y"} → 'a=1 b="x y"'. 단위는 키 이름 끝에 붙어 있다 (_ms _kb _dbm _pct)."""
    out = []
    for k, v in fields.items():
        v = mask(k, v)
        if isinstance(v, bool) or v is None:
            text = json.dumps(v)
        elif isinstance(v, float):
            text = f"{v:g}"
        elif isinstance(v, (int, str)) and " " not in str(v) and str(v) != "":
            text = str(v)
        else:
            text = json.dumps(v, ensure_ascii=False)
        out.append(f"{k}={text}")
    return " ".join(out)


@dataclass
class FaceWindow:
    started: float = 0.0          # 창의 첫 메시지 시각
    last_at: float = 0.0          # 창의 마지막 메시지 시각
    msgs: int = 0
    face_true: int = 0
    lost: int = 0
    resets: int = 0
    infer_sum: float = 0.0
    infer_n: int = 0
    infer_max: float = 0.0
    last_seq: int | None = None   # 요약 창이 바뀌어도 이어서 본다 (창 경계의 유실도 센다)


class Recorder:
    def __init__(self, timeline, publish, clock=time.time, face_every_s=5.0, ping_every_s=30.0,
                 pong_wait_s=5.0, sys_every_s=60.0, face_max_per_s=10):
        self.timeline, self.publish, self.clock = timeline, publish, clock
        self.face_every_s, self.ping_every_s, self.pong_wait_s = face_every_s, ping_every_s, pong_wait_s
        self.sys_every_s, self.face_max_per_s = sys_every_s, face_max_per_s
        self.lock = threading.Lock()   # on_message(MQTT 스레드)와 tick(주 스레드)이 함께 쓴다
        self.faces: dict[str, FaceWindow] = {}
        self.ping_due: dict[str, float] = {}           # 기기 → 다음 ping 시각
        self.pending: dict[int, tuple[str, float]] = {}  # ping id → (기기, 보낸 시각)
        self.no_pong: set[str] = set()                   # "pong 없음"을 이미 알린 기기 (반복해서 쓰지 않는다)
        self.next_id = 0
        self.sys: dict[str, float] = {}
        self.sys_next = clock() + sys_every_s
        self.topic_counts: Counter = Counter()
        self.stats = {"received": 0, "bad": 0}

    # ── 받기 ──

    def on_message(self, topic: str, payload: bytes, retain: bool = False, qos: int = 0, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self.lock:
            self.stats["received"] += 1
            if topic.startswith("$SYS/"):
                self._sys(topic, payload, now)
                return
            parts = topic.split("/")
            if len(parts) < 3 or parts[0] != "zt" or not payload:   # 빈 본문은 retain 지우기
                return
            device, kind = parts[1], parts[2]
            self.topic_counts[kind] += 1
            try:
                body = json.loads(payload)
            except ValueError:
                body = None
            self.timeline.raw(now, topic, body if body is not None else payload.decode("utf-8", "replace"), retain, qos)
            if not isinstance(body, dict):
                self.stats["bad"] += 1
                mqtt_log.warning("JSON 객체가 아닌 메시지 topic=%s", topic)
            elif kind == "log":
                self._log(device, parts[3] if len(parts) > 3 else "", body, now)
            elif kind == "face":
                self._face(device, body, now)
            elif kind == "pong":
                self._pong(device, body, now)
            elif kind != "ping":       # 자기가 보낸 ping은 원문에만 남는다
                self._traffic(device, kind, body, retain, now)

    def _log(self, device: str, part: str, body: dict, now: float) -> None:
        level = LEVELS.get(body.get("level"))
        logger, where, msg = body.get("logger"), body.get("where"), body.get("msg")
        fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
        problem = ("level" if level is None else
                   "logger" if not isinstance(logger, str) or not LOGGER_NAME.match(logger) else
                   "where" if not isinstance(where, str) or not where else
                   "msg" if not isinstance(msg, str) or not msg else None)
        if problem:
            self.stats["bad"] += 1
            mqtt_log.warning("형식이 틀린 log device=%s part=%s reason=%s level=%s", device, part, problem, body.get("level"))
            return
        extra = {} if device == "server" else {"device": device}
        extra.update(fields)
        if isinstance(body.get("up_ms"), int):
            extra["up_ms"] = body["up_ms"]
        if part and not logger.startswith(f"zt.{part}"):
            extra["topic_part"] = part   # 토픽의 파트와 로거 이름이 다르면 드러나게
        text = f"{msg} {kv(extra)}" if extra else msg
        ts = body.get("ts_ms")
        # PC에서 도는 파트는 보낸 시각을 쓴다. 시계가 크게 어긋나면(1시간 넘게) 받은 시각으로 둔다
        t = ts / 1000 if isinstance(ts, int) and abs(ts / 1000 - now) < 3600 else now
        self.timeline.foreign(level, logger, where, text, t)

    def _face(self, device: str, body: dict, now: float) -> None:
        w = self.faces.setdefault(device, FaceWindow())
        if w.msgs == 0:
            w.started = now
        seq = body.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            if w.last_seq is not None:
                if seq > w.last_seq + 1:
                    w.lost += seq - w.last_seq - 1
                elif seq <= w.last_seq:
                    w.resets += 1
                    face_log.warning("face seq가 처음부터 (재부팅?) device=%s seq=%s last_seq=%s", device, seq, w.last_seq)
            w.last_seq = seq
        w.msgs += 1
        w.last_at = now
        w.face_true += body.get("face") is True
        infer = body.get("infer_ms")
        if isinstance(infer, (int, float)) and not isinstance(infer, bool):
            w.infer_sum += infer
            w.infer_n += 1
            w.infer_max = max(w.infer_max, infer)

    def _pong(self, device: str, body: dict, now: float) -> None:
        pid = body.get("id")
        sent = self.pending.get(pid) if isinstance(pid, int) else None
        if not sent or sent[0] != device:
            mqtt_log.debug("모르는 pong device=%s id=%s", device, pid)
            return
        del self.pending[pid]
        rtt_ms = (now - sent[1]) * 1000
        self.no_pong.discard(device)
        ping_log.info("ping 왕복 device=%s rtt_ms=%d one_way_ms=%d", device, round(rtt_ms), round(rtt_ms / 2))

    def _traffic(self, device: str, kind: str, body: dict, retain: bool, now: float) -> None:
        fields = dict(body)
        if retain:
            fields["retain"] = 1   # 접속할 때 받은 지난 상태
        if kind == "status":
            state = body.get("state")
            if state == "offline":
                self.ping_due.pop(device, None)
                self.no_pong.discard(device)
                if not retain:   # 지금 끊김. retain으로 받은 지난 offline은 INFO로만
                    mqtt_log.warning("기기 끊김 (LWT offline) device=%s", device)
                    return
            elif state in ("idle", "running") and device != "server" and device not in self.ping_due:
                self.ping_due[device] = now   # 처음 본 기기는 바로 ping
        mqtt_log.info("%s 받음 device=%s %s", kind, device, kv(fields))

    def _sys(self, topic: str, payload: bytes, now: float) -> None:
        text = payload.decode("utf-8", "replace").strip()
        if topic.startswith("$SYS/broker/log/"):
            level = BROKER_LEVELS.get(topic.rsplit("/", 1)[-1], logging.INFO)
            text = BROKER_TIME.sub("", text)
            # broker 헬스체크(10초마다 접속)와 "New connection" 줄은 DEBUG로 낮춘다. 누가 붙었는지는 다음 줄에 나온다
            if re.search(r"\bhealthcheck\b", text) or text.startswith("New connection from"):
                level = logging.DEBUG
            self.timeline.foreign(level, "zt.broker", "mosquitto", text, now)
            return
        key = SYS_KEYS.get(topic[len("$SYS/broker/"):])
        if key:
            m = re.match(r"[\d.]+", text)
            if m:
                self.sys[key] = float(m.group())

    # ── 주기적으로 ──

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        pings = []
        with self.lock:
            self._face_summaries(now)
            pings = self._pings(now)
            if now >= self.sys_next:
                self._sys_summary(now)
        for topic, body in pings:   # 잠금 밖에서 보낸다
            self.publish(topic, json.dumps(body))

    def _face_summaries(self, now: float) -> None:
        for device, w in self.faces.items():
            if not w.msgs or now - w.started < self.face_every_s:
                continue
            # 메시지가 실제로 온 구간의 속도 (계약: 초당 10개 이하). 중간에 멈춘 창도 5초로 나누지 않는다
            span = w.last_at - w.started
            per_s = (w.msgs - 1) / span if w.msgs > 1 and span > 0 else w.msgs / self.face_every_s
            fields = {"device": device, "msgs": w.msgs, "per_s": round(per_s, 1), "face_true": w.face_true, "lost": w.lost}
            if w.infer_n:
                fields.update(infer_ms_avg=round(w.infer_sum / w.infer_n), infer_ms_max=round(w.infer_max))
            if w.resets:
                fields["seq_reset"] = w.resets
            face_log.info("face 요약 %s", kv(fields))
            if per_s > self.face_max_per_s * 1.2:
                face_log.warning("face가 계약(초당 %d개)보다 많음 device=%s per_s=%.1f", self.face_max_per_s, device, per_s)
            self.faces[device] = FaceWindow(last_seq=w.last_seq)

    def _pings(self, now: float) -> list:
        out = []
        for device, due in list(self.ping_due.items()):
            if now >= due:
                self.next_id += 1
                self.pending[self.next_id] = (device, now)
                self.ping_due[device] = now + self.ping_every_s
                out.append((f"zt/{device}/ping", {"id": self.next_id}))
        for pid, (device, sent) in list(self.pending.items()):
            if now - sent > self.pong_wait_s:
                del self.pending[pid]
                if device not in self.no_pong:
                    self.no_pong.add(device)
                    ping_log.info("pong 없음 device=%s wait_s=%g (face-detector가 ping을 아직 지원하지 않거나 끊김. 다시 오면 알린다)",
                                  device, self.pong_wait_s)
        return out

    def _sys_summary(self, now: float) -> None:
        span = self.sys_every_s + (now - self.sys_next)
        if self.sys:
            broker_log.info("broker 요약 %s", kv({k: (int(v) if float(v).is_integer() else round(v, 2)) for k, v in self.sys.items()}))
        if self.topic_counts:
            rates = {f"{k}_per_s": round(c / max(span, 1e-6), 2) for k, c in sorted(self.topic_counts.items())}
            mqtt_log.info("토픽별 초당 메시지 %s", kv(rates))
        self.topic_counts.clear()
        self.sys_next = now + self.sys_every_s
