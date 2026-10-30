"""broker (B1~B4). docker compose up으로 띄운 broker를 쓴다."""
import json
import os
import time

import pytest

from helpers import Probe, topic, unique_device, validate


@pytest.mark.feature("B1")
def test_publish_and_receive(broker):
    t = f"smoke/{os.getpid()}/b1"  # 계약 토픽(zt/) 밖: 다른 서비스가 받지 않는다
    p = Probe(broker["host"], broker["mqtt_port"], "b1")
    assert p.start(), p.failed
    p.subscribe(t)
    p.publish(t, {"n": 1})
    assert p.expect(t, lambda m: m.get("n") == 1, timeout=3)
    p.stop()


@pytest.mark.feature("B2")
def test_status_is_retained(broker):
    """player가 나중에 접속해도 마지막 status를 바로 받는다 (계약: status retain)."""
    device = unique_device("b2")
    t = topic(device, "status")
    board = Probe(broker["host"], broker["mqtt_port"], "b2-board")
    assert board.start()
    board.publish(t, {"state": "idle", "fw": "0.1.0"}, retain=True)
    board.stop()
    late = Probe(broker["host"], broker["mqtt_port"], "b2-player")
    assert late.start()
    late.subscribe(t)
    got = late.next(t, timeout=3)
    late.publish(t, b"", retain=True)
    late.stop()
    assert got and got[1] == {"state": "idle", "fw": "0.1.0"} and got[2] is True


@pytest.mark.feature("B3")
def test_last_will_offline(broker):
    """face-detector처럼 LWT를 걸고 인사 없이 끊기면 broker가 {"state":"offline"}을 retain으로 보낸다."""
    device = unique_device("b3")
    t = topic(device, "status")
    watcher = Probe(broker["host"], broker["mqtt_port"], "b3-watch")
    board = Probe(broker["host"], broker["mqtt_port"], "b3-board", will=(t, json.dumps({"state": "offline"}), 1, True), keepalive=1)
    assert watcher.start() and board.start()
    watcher.subscribe(t)
    board.publish(t, {"state": "running", "fw": "0.1.0"}, retain=True)
    assert watcher.expect(t, lambda m: m.get("state") == "running", timeout=3)
    board.client.loop_stop()
    board.client.socket().close()  # 전원이 꺼진 보드
    offline = watcher.next(t, lambda m: m.get("state") == "offline", timeout=6)
    watcher.publish(t, b"", retain=True)
    watcher.stop()
    assert offline, "LWT(offline)가 오지 않음"
    validate("status", offline[1])


@pytest.mark.feature("B4")
def test_websocket_through_player(player):
    """브라우저는 player의 /mqtt로 broker:9001(WebSocket)에 붙는다."""
    t = f"smoke/{os.getpid()}/b4"
    ws = Probe(player["host"], player["player_port"], "b4", transport="websockets", ws_path="/mqtt")
    assert ws.start(), f"ws://{player['host']}:{player['player_port']}/mqtt 접속 실패 ({ws.failed})"
    ws.subscribe(t)
    ws.publish(t, {"ws": True})
    assert ws.expect(t, lambda m: m.get("ws") is True, timeout=3)
    ws.stop()
