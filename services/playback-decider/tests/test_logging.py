import json
import logging

import pytest

from app import main
from app.decider import Decider
from app.mqtt_log import MqttLogHandler, kv


class FakeClient:
    def __init__(self, connected=True):
        self.connected, self.sent = connected, []

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload, qos=0):
        self.sent.append((topic, json.loads(payload), qos))


@pytest.fixture
def mqtt_log():
    client = FakeClient()
    handler = MqttLogHandler(client)
    logger = logging.getLogger("zt.playback-decider")
    logger.addHandler(handler)
    old = logger.level
    logger.setLevel(logging.DEBUG)
    yield client
    logger.removeHandler(handler)
    logger.setLevel(old)


def test_kv_line_and_mqtt_body(mqtt_log, caplog):
    log = logging.getLogger("zt.playback-decider.test")
    with caplog.at_level(logging.INFO, logger="zt.playback-decider"):
        kv(log, logging.INFO, "play 판정", device="esp32-a", seq=12, reason="face_present", present_ms=612)
    assert caplog.records[-1].getMessage() == "play 판정 device=esp32-a seq=12 reason=face_present present_ms=612"
    assert caplog.records[-1].filename == "test_logging.py"  # kv()가 아니라 부른 곳

    topic, body, qos = mqtt_log.sent[-1]
    assert topic == "zt/esp32-a/log/playback-decider" and qos == 0
    assert body["level"] == "INFO" and body["logger"] == "zt.playback-decider.test"
    assert body["msg"] == "play 판정" and body["where"].startswith("test_logging.py:")
    assert body["fields"] == {"device": "esp32-a", "seq": 12, "reason": "face_present", "present_ms": 612}  # kv에 준 그대로
    assert isinstance(body["ts_ms"], int)


def test_no_device_goes_to_server_topic(mqtt_log):
    kv(logging.getLogger("zt.playback-decider.main"), logging.INFO, "broker 연결됨", host="broker")
    assert mqtt_log.sent[-1][0] == "zt/server/log/playback-decider"


def test_debug_and_disconnected_are_not_sent(mqtt_log):
    log = logging.getLogger("zt.playback-decider.test")
    kv(log, logging.DEBUG, "face", device="esp32-a")
    assert mqtt_log.sent == []
    mqtt_log.connected = False
    kv(log, logging.INFO, "play 판정", device="esp32-a")
    assert mqtt_log.sent == []


def test_decision_reasons(mqtt_log):
    d = Decider(play_after_ms=500, pause_after_ms=1500, min_score=0.6, device="esp32-a")
    d.reset(running=True, now_ms=0)
    for t in range(0, 601, 100):
        d.update(True, 0.9, t, seq=t // 100)
    for t in range(700, 2301, 100):
        d.update(False, 0.0, t, seq=t // 100)
    d.update(True, 0.9, 3000, seq=30)
    d.update(True, 0.9, 3500, seq=31)  # play
    assert d.tick(5000) == "pause"     # 1.5초 동안 메시지 없음
    assert [b["fields"]["reason"] for _, b, _ in mqtt_log.sent] == ["face_present", "face_absent", "face_present", "face_timeout"]
    last = mqtt_log.sent[-1][1]["fields"]
    assert last["seq"] == 31 and last["silent_ms"] == 1500  # 끊겨서 내린 판정은 마지막으로 받은 seq


def test_seq_gap_and_reboot(mqtt_log):
    main.last_seqs.clear()
    for seq in (5, 6, 9, 0):
        main.check_seq("esp32-a", seq)
    msgs = [(b["level"], b["msg"], b["fields"]) for _, b, _ in mqtt_log.sent]
    assert msgs[0] == ("WARNING", "seq 건너뜀", {"device": "esp32-a", "expected": 7, "got": 9, "lost": 2})
    assert msgs[1][1].startswith("seq가 줄어듦") and msgs[1][2]["got"] == 0
    assert len(msgs) == 2


def test_bad_messages_are_summarized(mqtt_log):
    main.bad_counts.clear()
    for _ in range(7):
        main.bad("esp32-a", "face", "type")
    main.bad("esp32-a", "control", "cmd")
    assert mqtt_log.sent == []  # 바로 찍지 않고 모은다
    main.flush_bad()
    got = {b["fields"]["topic"]: b["fields"]["count"] for _, b, _ in mqtt_log.sent}
    assert got == {"zt/esp32-a/face": 7, "zt/esp32-a/control": 1}
    assert main.bad_counts == {}


def test_handle_logs_control(mqtt_log):
    main.handle("zt/esp32-z/control", b'{"cmd": "start"}')
    _, body, _ = mqtt_log.sent[-1]
    assert body["msg"] == "control 받음, 판정 초기화" and body["fields"] == {"device": "esp32-z", "cmd": "start"}
    main.deciders.pop("esp32-z", None)


def test_decision_fields_have_action(mqtt_log):
    d = Decider(play_after_ms=0, pause_after_ms=0, min_score=0.6, device="esp32-a")
    d.update(True, 0.9, 0, seq=1)
    assert mqtt_log.sent[-1][1]["fields"]["action"] == "play"
