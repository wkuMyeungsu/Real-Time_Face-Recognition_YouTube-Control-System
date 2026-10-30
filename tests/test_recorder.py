"""recorder (R1~R7): 모든 파트의 로그를 logs/zt.log 한 타임라인에 모은다.

기준: docs/logging-design.txt (3장 한 줄 형식, 5장 recorder, 6장 ping·pong), docs/contracts/README.md의 log·ping·pong 절.
recorder는 docker-compose.yml에서 저장소의 ./logs에 쓰므로 테스트는 그 파일을 읽어 확인한다.
"""
import json
import random
import re
import time

import pytest

from helpers import LogTail, Probe, http_json, topic, unique_device, validate

# 2026-10-30 14:05:07,502 INFO     zt.face-detector.wifi face-detector.ino:62 연결됨 device=esp32-a …
LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} (INFO|WARNING|ERROR|CRITICAL) +(zt\.[\w.-]+) (\S+) (.*)$")


@pytest.fixture
def probe(recorder):
    p = Probe(recorder["host"], recorder["mqtt_port"], "rec")
    assert p.start(), p.failed
    yield p
    p.stop()


def mine(device):
    return lambda line: f"device={device} " in f"{line} "


@pytest.mark.feature("R1")
def test_health(recorder):
    status, body = http_json(f"http://{recorder['host']}:{recorder['recorder_port']}/health")
    assert status == 200 and body.get("ok") is True and body.get("mqtt") is True


@pytest.mark.feature("R2")
def test_messages_become_timeline_lines(probe):
    """control·playback을 받은 시각(밀리초)·레벨·로거·위치·본문의 한 줄로 남긴다."""
    device, tail = unique_device("r2"), LogTail()
    probe.publish(topic(device, "control"), {"cmd": "start"})
    probe.publish(topic(device, "playback"), {"action": "play"})
    control = tail.wait(lambda l: mine(device)(l) and "cmd=start" in l)
    playback = tail.wait(lambda l: mine(device)(l) and "action=play" in l)
    assert control and playback, f"logs/zt.log에 줄이 없음: {tail.lines()[-5:]}"
    m = LINE.match(control)
    assert m, f"한 줄 형식이 아님: {control}"
    assert m.group(1) == "INFO" and m.group(2).startswith("zt.recorder") and re.match(r"\S+\.py:\d+$", m.group(3))


@pytest.mark.feature("R3")
def test_log_topic_keeps_sender_and_hides_secrets(probe):
    """log 토픽은 보낸 파트의 레벨·로거·위치 그대로 옮기고, 비밀값은 앞 두 글자만 남긴다. 계약에 안 맞으면 옮기지 않고 알린다."""
    device, tail = unique_device("r3"), LogTail()
    body = {"level": "WARNING", "logger": "zt.face-detector.mqtt", "where": "face-detector.ino:88", "msg": "재연결",
            "up_ms": 4321, "fields": {"rc": -2, "count": 3, "wifi_password": "hunter22"}}
    validate("log", body)
    probe.publish(f"zt/{device}/log/face-detector", body, qos=0)
    line = tail.wait(lambda l: mine(device)(l) and "재연결" in l)
    assert line, "log 토픽이 logs/zt.log에 옮겨지지 않음"
    m = LINE.match(line)
    assert m and m.groups()[:3] == ("WARNING", "zt.face-detector.mqtt", "face-detector.ino:88"), line
    assert "rc=-2 count=3" in line and "up_ms=4321" in line
    assert "hunter22" not in line and "wifi_password=hu***" in line
    probe.publish(f"zt/{device}/log/face-detector", {**body, "level": "DEBUG", "msg": "프레임"}, qos=0)
    warned = tail.wait(lambda l: "형식이 틀린 log" in l and mine(device)(l))
    assert warned and "reason=level" in warned, "DEBUG(계약 위반)를 알리지 않음"
    assert not any("프레임" in l for l in tail.lines())


@pytest.mark.feature("R4")
def test_face_raw_in_jsonl_summary_in_log(probe):
    """face 원문은 zt.jsonl에만, zt.log에는 5초 요약 (받은 수, seq 건너뜀)."""
    device, tail, raw = unique_device("r4"), LogTail(), LogTail("zt.jsonl")
    seqs = [s for s in range(30) if s not in (7, 8, 9)]
    for s in seqs:
        probe.publish(topic(device, "face"), {"seq": s, "face": True, "score": 0.9, "count": 1, "infer_ms": 95}, qos=0)
        time.sleep(0.05)
    summary = tail.wait(lambda l: "face 요약" in l and mine(device)(l), timeout=9)
    assert summary, "5초 안에 face 요약이 없음"
    assert f"msgs={len(seqs)}" in summary and "lost=3" in summary and "infer_ms_avg=95" in summary, summary
    assert not [l for l in tail.lines() if mine(device)(l) and "seq=" in l], "face 원문이 zt.log에 들어감"
    faces = [json.loads(l) for l in raw.lines() if f'"zt/{device}/face"' in l]
    assert [f["payload"]["seq"] for f in faces] == seqs


@pytest.mark.feature("R5")
def test_ping_pong_round_trip(recorder):
    """처음 본 기기(status idle)에 ping을 보내고, pong이 오면 왕복 시간 rtt_ms를 남긴다."""
    device, tail = unique_device("r5"), LogTail()
    board = Probe(recorder["host"], recorder["mqtt_port"], "r5-board")
    assert board.start()
    board.subscribe(topic(device, "ping"))
    board.publish(topic(device, "status"), {"state": "idle", "fw": "0.1.0"})
    ping = board.next(topic(device, "ping"), timeout=3)
    if ping:
        validate("ping", ping[1])
        board.publish(topic(device, "pong"), ping[1], qos=0)
    line = tail.wait(lambda l: "ping 왕복" in l and mine(device)(l))
    board.publish(topic(device, "status"), {"state": "offline"})   # recorder가 이 기기를 잊게 (30초마다 ping하지 않게)
    board.stop()
    assert ping, "status idle을 받고도 ping을 보내지 않음"
    assert line and re.search(r"rtt_ms=\d+ one_way_ms=\d+", line), line


@pytest.mark.feature("R6")
def test_lost_board_is_warning(recorder):
    """보드가 인사 없이 끊겨 LWT(offline)가 나가면 WARNING으로 남긴다 (LWT 발동 확인)."""
    device, tail = unique_device("r6"), LogTail()
    t = topic(device, "status")
    board = Probe(recorder["host"], recorder["mqtt_port"], "r6-board", will=(t, json.dumps({"state": "offline"}), 1, True), keepalive=1)
    assert board.start()
    board.publish(t, {"state": "running", "fw": "0.1.0"}, retain=True)
    board.client.loop_stop()
    board.client.socket().close()   # 전원이 꺼진 보드
    line = tail.wait(lambda l: "기기 끊김" in l and mine(device)(l), timeout=6)
    cleaner = Probe(recorder["host"], recorder["mqtt_port"], "r6-clean")
    if cleaner.start():
        cleaner.publish(t, b"", retain=True)
        cleaner.stop()
    assert line, "LWT offline이 타임라인에 없음"
    assert LINE.match(line).group(1) == "WARNING"


@pytest.mark.feature("R7")
def test_broker_log_in_same_timeline(recorder):
    """broker(mosquitto)의 접속·끊김 로그도 같은 타임라인에 zt.broker로 들어온다 (mosquitto.conf의 log_dest topic)."""
    tail, name = LogTail(), f"r7x{random.randint(1000, 9999)}"
    p = Probe(recorder["host"], recorder["mqtt_port"], name)
    assert p.start()
    p.stop()
    line = tail.wait(lambda l: " zt.broker " in l and f"test-{name}-" in l and "connected" in l)
    assert line, "broker 접속 로그가 타임라인에 없음"
    assert LINE.match(line).group(3) == "mosquitto"
