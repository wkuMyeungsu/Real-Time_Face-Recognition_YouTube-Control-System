"""recorder 단위 테스트. MQTT 없이 시계와 publish를 바꿔 끼운다. CI: docker compose run recorder pytest -q"""
import json
import logging
import re

import pytest

from app import log_config
from app.recorder import Recorder, kv, mask
from app.timeline import Timeline

LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} (DEBUG|INFO|WARNING|ERROR|CRITICAL) +(zt\.\S+) (\S+) (.*)$")


class FakeTimeline:
    def __init__(self):
        self.foreign_lines, self.raw_lines = [], []
        self.path = "fake"

    def foreign(self, level, logger, where, msg, t):
        self.foreign_lines.append((level, logger, where, msg, t))

    def raw(self, t, topic, payload, retain, qos):
        self.raw_lines.append((topic, payload, retain, qos))


@pytest.fixture
def rec(caplog):
    caplog.set_level(logging.DEBUG, logger="zt")
    sent = []
    r = Recorder(FakeTimeline(), publish=lambda t, p: sent.append((t, json.loads(p))), clock=lambda: 1000.0,
                 face_every_s=5, ping_every_s=30, pong_wait_s=5, sys_every_s=60)
    r.sent = sent
    return r


def msgs(caplog, name):
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == name]


def send(r, topic, body, now, retain=False):
    r.on_message(topic, json.dumps(body).encode() if not isinstance(body, bytes) else body, retain, 0, now=now)


def test_kv_and_mask():
    assert kv({"a": 1, "b": "x y", "c": 0.5, "d": True}) == 'a=1 b="x y" c=0.5 d=true'
    assert mask("WIFI_PASSWORD", "secret123") == "se***" and mask("token", "ab") == "ab***" and mask("ssid", "home") == "home"


def test_log_topic_keeps_sender_level_logger_where(rec):
    send(rec, "zt/esp32-a/log/face-detector", {"level": "WARNING", "logger": "zt.face-detector.wifi", "where": "face-detector.ino:62",
                                               "msg": "재연결", "up_ms": 12345, "fields": {"rc": -2, "count": 3, "wifi_password": "abcdef"}}, 1000.0)
    level, logger, where, msg, t = rec.timeline.foreign_lines[-1]
    assert (level, logger, where, t) == (logging.WARNING, "zt.face-detector.wifi", "face-detector.ino:62", 1000.0)
    assert msg == "재연결 device=esp32-a rc=-2 count=3 wifi_password=ab*** up_ms=12345"


def test_log_uses_sender_ts_ms_on_server(rec):
    send(rec, "zt/server/log/playback-decider", {"level": "INFO", "logger": "zt.playback-decider.main", "where": "main.py:9",
                                                 "msg": "시작", "ts_ms": 999_500}, 1000.0)
    _, _, _, msg, t = rec.timeline.foreign_lines[-1]
    assert msg == "시작" and t == 999.5   # server는 device를 붙이지 않고, PC 시계 ts_ms를 쓴다


@pytest.mark.parametrize("body, reason", [
    ({"level": "DEBUG", "logger": "zt.player.mqtt", "where": "app.js:x", "msg": "m"}, "level"),
    ({"level": "INFO", "logger": "player", "where": "app.js:x", "msg": "m"}, "logger"),
    ({"level": "INFO", "logger": "zt.player.mqtt", "where": "", "msg": "m"}, "where"),
])
def test_bad_log_is_reported_not_copied(rec, caplog, body, reason):
    send(rec, "zt/esp32-a/log/player", body, 1000.0)
    assert not rec.timeline.foreign_lines
    assert any(f"reason={reason}" in m for lv, m in msgs(caplog, "zt.recorder.mqtt") if lv == logging.WARNING)


def test_face_raw_only_then_five_second_summary(rec, caplog):
    seqs = [0, 1, 2, 5, 6, 7, 8, 9]   # 3·4 유실
    for i, s in enumerate(seqs):
        send(rec, "zt/esp32-a/face", {"seq": s, "face": s >= 5, "score": 0.9, "count": 1, "infer_ms": 90 + i}, 1000.0 + i * 0.1)
    assert len([x for x in rec.timeline.raw_lines if x[0].endswith("/face")]) == len(seqs)
    rec.tick(now=1004.0)
    assert not msgs(caplog, "zt.recorder.face")   # 5초 전에는 요약 없음
    rec.tick(now=1005.0)
    (level, text), = msgs(caplog, "zt.recorder.face")
    assert level == logging.INFO and "device=esp32-a msgs=8" in text and "face_true=5" in text and "lost=2" in text
    assert "per_s=10" in text   # 0.7초 동안 8개 = 실제로 온 구간의 속도 (5초로 나누지 않는다)
    assert "infer_ms_avg=94 infer_ms_max=97" in text


def test_face_seq_reset_and_rate_warning(rec, caplog):
    for i in range(80):   # 5초에 80개 → 초당 16개
        send(rec, "zt/esp32-b/face", {"seq": i % 40, "face": False, "score": 0, "count": 0, "infer_ms": 9}, 1000.0 + i / 16)
    rec.tick(now=1005.0)
    warnings = [m for lv, m in msgs(caplog, "zt.recorder.face") if lv == logging.WARNING]
    assert any("처음부터" in m for m in warnings) and any("계약" in m for m in warnings)


def test_ping_on_first_status_then_pong_rtt(rec, caplog):
    send(rec, "zt/esp32-a/status", {"state": "idle", "fw": "0.1.0"}, 1000.0)
    rec.tick(now=1000.0)
    assert rec.sent == [("zt/esp32-a/ping", {"id": 1})]
    send(rec, "zt/esp32-a/pong", {"id": 1}, 1000.084)
    assert any("ping 왕복 device=esp32-a rtt_ms=84 one_way_ms=42" in m for _, m in msgs(caplog, "zt.recorder.ping"))
    rec.tick(now=1029.0)
    assert len(rec.sent) == 1
    rec.tick(now=1030.0)
    assert rec.sent[-1] == ("zt/esp32-a/ping", {"id": 2})   # 30초마다


def test_no_pong_reported_once(rec, caplog):
    send(rec, "zt/esp32-a/status", {"state": "running", "fw": "0.1.0"}, 1000.0)
    for now in (1000.0, 1006.0, 1030.0, 1036.0):
        rec.tick(now=now)
    assert len([m for _, m in msgs(caplog, "zt.recorder.ping") if "pong 없음" in m]) == 1


def test_status_offline_live_is_warning_retained_is_info(rec, caplog):
    send(rec, "zt/esp32-a/status", {"state": "offline"}, 1000.0, retain=True)
    send(rec, "zt/esp32-a/status", {"state": "offline"}, 1001.0)
    lines = msgs(caplog, "zt.recorder.mqtt")
    assert (logging.INFO, "status 받음 device=esp32-a state=offline retain=1") in lines
    assert (logging.WARNING, "기기 끊김 (LWT offline) device=esp32-a") in lines


def test_control_playback_lines_and_ignored(rec, caplog):
    send(rec, "zt/esp32-a/control", {"cmd": "start"}, 1000.0)
    send(rec, "zt/esp32-a/playback", {"action": "play"}, 1000.0)
    rec.on_message("zt/esp32-a/status", b"", True, 1, now=1000.0)   # retain 지우기는 무시
    rec.on_message("zt/esp32-a/face", b"not json", False, 0, now=1000.0)
    lines = msgs(caplog, "zt.recorder.mqtt")
    assert (logging.INFO, "control 받음 device=esp32-a cmd=start") in lines
    assert (logging.INFO, "playback 받음 device=esp32-a action=play") in lines
    assert any(lv == logging.WARNING and "JSON" in m for lv, m in lines)


def test_broker_log_and_sys_summary(rec, caplog):
    rec.on_message("$SYS/broker/log/N", b"2026-10-30 14:16:07: New client connected from 172.18.0.1:5 as esp32-a (p2, c1, k60).", now=1000.0)
    rec.on_message("$SYS/broker/log/N", b"2026-10-30 14:16:07: New client connected from 127.0.0.1:6 as healthcheck (p2, c1, k60).", now=1000.0)
    (lv1, name, where, msg1, _), (lv2, *_rest) = rec.timeline.foreign_lines
    assert (lv1, name, where) == (logging.INFO, "zt.broker", "mosquitto") and msg1.startswith("New client connected") and lv2 == logging.DEBUG
    for topic, value in [("clients/connected", b"3"), ("load/messages/received/1min", b"52.31"), ("uptime", b"120 seconds")]:
        rec.on_message(f"$SYS/broker/{topic}", value, now=1000.0)
    send(rec, "zt/esp32-a/control", {"cmd": "start"}, 1000.0)
    rec.tick(now=1059.0)
    assert not msgs(caplog, "zt.broker")
    rec.tick(now=1060.0)
    assert msgs(caplog, "zt.broker") == [(logging.INFO, "broker 요약 clients=3 msgs_recv_per_min=52.31 uptime_s=120")]
    assert any("control_per_s=" in m for _, m in msgs(caplog, "zt.recorder.mqtt"))


def test_timeline_file_format_and_rotation(tmp_path):
    tl = Timeline(tmp_path, max_mb=0.001, backups=2)   # 1KB마다 돌린다
    tl.attach("zt")
    try:
        logging.getLogger("zt").setLevel(logging.INFO)
        logging.getLogger("zt.recorder.test").info("자기 로그 a=%s", 1)
        tl.foreign(logging.WARNING, "zt.face-detector.wifi", "face-detector.ino:62", "재연결 rc=-2", 1_761_800_707.502)
        tl.foreign(logging.DEBUG, "zt.broker", "mosquitto", "보이지 않음", 1_761_800_707.6)
        tl.raw(1_761_800_707.5, "zt/esp32-a/face", {"seq": 1}, False, 0)
        lines = (tmp_path / "zt.log").read_text(encoding="utf-8").splitlines()
        own, other = (LINE.match(x) for x in lines)
        assert own and own.group(2) == "zt.recorder.test" and re.match(r"test_recorder\.py:\d+", own.group(3))
        assert other.groups()[1:] == ("zt.face-detector.wifi", "face-detector.ino:62", "재연결 rc=-2")
        assert other.group(0).startswith("2025-10-30 14:05:07,502") or other.group(0).startswith("2025-10-30 05:05:07,502")
        assert len(lines) == 2   # DEBUG는 prod 타임라인에 쓰지 않는다
        assert json.loads((tmp_path / "zt.jsonl").read_text(encoding="utf-8"))["payload"] == {"seq": 1}
        for i in range(60):
            tl.foreign(logging.INFO, "zt.broker", "mosquitto", "x" * 40, 1_761_800_708 + i)
        assert (tmp_path / "zt.log.1").exists() and (tmp_path / "zt.log.2").exists() and not (tmp_path / "zt.log.3").exists()
    finally:
        tl.close()


def test_log_config_env_and_timezone(monkeypatch):
    assert log_config.build_config("dev")["loggers"]["zt"]["level"] == "DEBUG"
    monkeypatch.delenv("LOG_ENV", raising=False)
    cfg = log_config.build_config()
    assert cfg["loggers"]["zt"]["level"] == "INFO" and cfg["loggers"]["uvicorn.access"]["level"] == "WARNING"
    record = logging.LogRecord("zt.x", logging.INFO, "f.py", 1, "m", None, None)
    record.created, record.msecs = 1_761_800_707.502, 502
    assert log_config.ZtFormatter(tz="Asia/Seoul").formatTime(record) == "2025-10-30 14:05:07,502"
