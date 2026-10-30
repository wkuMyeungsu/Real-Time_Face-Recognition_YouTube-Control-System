"""player (P1~P11). 브라우저(Playwright)로 페이지를 열어 확인한다. 유튜브는 가짜 플레이어로 바꾼다.

기준: README의 player 설명("유튜브 플레이어, 시작·중지 버튼, 판정대로 재생·정지 실행, /mqtt를 broker로 넘김"),
docs/contracts/README.md의 control·status·playback 절, index.html의 요소 id.
"""
import time

import pytest

from contract_doc import topic_table
from helpers import Probe, clear_retained, http_json, open_player, topic, unique_device, validate

IDS = ["device", "broker", "esp32", "start", "stop", "player"]


@pytest.fixture
def page(player, browser):
    device = unique_device("p")
    context, pg = open_player(browser, player, device)
    yield pg, device
    context.close()
    clear_retained(player, device)


def connected(pg):
    pg.wait_for_function("document.getElementById('broker').textContent.includes('연결됨')", timeout=8000)


@pytest.mark.feature("P1")
def test_health(player):
    status, body = http_json(f"http://{player['host']}:{player['player_port']}/health")
    assert status == 200 and body.get("ok") is True


@pytest.mark.feature("P2")
def test_page_and_elements(page):
    pg, device = page
    missing = [i for i in IDS if pg.query_selector(f"#{i}") is None]
    assert not missing, f"요소가 없음: {missing}"
    assert pg.text_content("#device") == device  # ?device= 로 기기를 고른다


@pytest.mark.feature("P3")
def test_mqtt_proxy(player):
    t = f"smoke/p3-{int(time.time())}/ping"
    ws = Probe(player["host"], player["player_port"], "p3", transport="websockets", ws_path="/mqtt")
    assert ws.start(), ws.failed
    ws.subscribe(t)
    ws.publish(t, {"ping": 1})
    assert ws.expect(t, timeout=3)
    ws.stop()


@pytest.mark.feature("P4")
def test_broker_connected_shown(page):
    pg, _ = page
    connected(pg)
    assert not pg.errors, f"페이지 스크립트 오류: {pg.errors}"


def _button_sends(page, cfg, button, cmd):
    pg, device = page
    connected(pg)
    t = topic(device, "control")
    probe = Probe(cfg["host"], cfg["mqtt_port"], f"p-{cmd}")
    assert probe.start()
    probe.subscribe(t)
    probe.drain()
    pg.click(f"#{button}")
    got = probe.next(t, lambda m: m.get("cmd") == cmd, timeout=3)
    probe.stop()
    assert got, f"#{button}를 눌렀는데 control {cmd}가 오지 않음"
    validate("control", got[1])
    rule = topic_table()["control"]
    assert got[3] == rule["qos"], f"control QoS가 문서({rule['qos']})와 다름"
    assert got[2] is False or rule["retain"]


@pytest.mark.feature("P5")
def test_start_button(page, cfg):
    _button_sends(page, cfg, "start", "start")


@pytest.mark.feature("P6")
def test_stop_button(page, cfg):
    _button_sends(page, cfg, "stop", "stop")


@pytest.mark.feature("P7")
def test_esp32_status_shown(page, cfg):
    pg, device = page
    connected(pg)
    probe = Probe(cfg["host"], cfg["mqtt_port"], "p7")
    assert probe.start()
    for state in ("idle", "running"):
        probe.publish(topic(device, "status"), {"state": state, "fw": "0.1.0"}, retain=True)
        pg.wait_for_function(f"document.getElementById('esp32').textContent.includes('{state}')", timeout=3000)
    probe.publish(topic(device, "status"), {"state": "offline"}, retain=True)  # LWT
    pg.wait_for_function("document.getElementById('esp32').textContent.includes('offline')", timeout=3000)
    probe.stop()


@pytest.mark.feature("P8")
def test_playback_controls_youtube(page, cfg):
    """playback play → 유튜브 IFrame 플레이어의 playVideo(), pause → pauseVideo()."""
    pg, device = page
    connected(pg)
    pg.wait_for_function("(window.__yt || []).some((c) => c[0] === 'new')", timeout=5000)  # new YT.Player(...)
    probe = Probe(cfg["host"], cfg["mqtt_port"], "p8")
    assert probe.start()
    probe.publish(topic(device, "playback"), {"action": "play"})
    pg.wait_for_function("(window.__yt || []).some((c) => c[0] === 'playVideo')", timeout=3000)
    probe.publish(topic(device, "playback"), {"action": "pause"})
    pg.wait_for_function("(window.__yt || []).some((c) => c[0] === 'pauseVideo')", timeout=3000)
    probe.stop()


@pytest.mark.feature("P9")
def test_button_logged_to_log_topic(page, cfg):
    """버튼 → control 보냄을 zt/<기기>/log/player에도 남긴다. 로거는 zt.player.* (docs/logging-design.txt 7-4)."""
    pg, device = page
    connected(pg)
    t = f"zt/{device}/log/player"
    probe = Probe(cfg["host"], cfg["mqtt_port"], "p9")
    assert probe.start()
    probe.subscribe(t)
    pg.click("#start")
    got = probe.expect(t, lambda m: str(m.get("logger", "")).startswith("zt.player"), timeout=3)
    probe.stop()
    assert got, "시작 버튼을 눌렀는데 log 토픽에 player 로그가 없음"
    validate("log", got)


def _idle_sends_start(pg, cfg, device, expect):
    """status idle을 보내고, 그 뒤 control start가 오는지(expect) 본다."""
    probe = Probe(cfg["host"], cfg["mqtt_port"], "p9")
    assert probe.start()
    probe.subscribe(topic(device, "control"))
    probe.drain()
    probe.publish(topic(device, "status"), {"state": "idle", "fw": "0.1.0"}, retain=True)
    pg.wait_for_function("document.getElementById('esp32').textContent.includes('idle')", timeout=3000)
    got = probe.next(topic(device, "control"), lambda m: m.get("cmd") == "start", timeout=2 if expect else 1.5)
    probe.stop()
    return got


@pytest.mark.feature("P10")
def test_restart_after_reboot(page, cfg):
    """시작을 누른 뒤 ESP32가 재부팅돼 idle이 오면 start를 다시 보낸다."""
    pg, device = page
    connected(pg)
    pg.click("#start")
    got = _idle_sends_start(pg, cfg, device, expect=True)
    assert got, "시작 상태에서 idle이 왔는데 control start를 다시 보내지 않음"
    validate("control", got[1])


@pytest.mark.feature("P10")
def test_no_restart_before_start(page, cfg):
    """페이지를 열기만 한 상태(시작 전)의 idle에는 start를 보내지 않는다."""
    pg, device = page
    connected(pg)
    assert not _idle_sends_start(pg, cfg, device, expect=False), "시작을 누르지 않았는데 start를 보냄"


@pytest.mark.feature("P10")
def test_no_restart_after_stop(page, cfg):
    """시작 → 중지 뒤의 idle(stop 응답)에는 start를 보내지 않는다."""
    pg, device = page
    connected(pg)
    pg.click("#start")
    pg.click("#stop")
    assert not _idle_sends_start(pg, cfg, device, expect=False), "중지 뒤 idle에 start를 다시 보냄"


@pytest.mark.feature("P11")
def test_resume_running_after_reload(player, browser, cfg):
    """감지 중(retain status running)에 페이지를 열면 시작 상태로 이어받고, 그 뒤 재부팅 idle에 start를 다시 보낸다."""
    device = unique_device("p11")
    probe = Probe(cfg["host"], cfg["mqtt_port"], "p11")
    assert probe.start()
    probe.publish(topic(device, "status"), {"state": "running", "fw": "0.1.0"}, retain=True)
    context, pg = open_player(browser, player, device)
    try:
        connected(pg)
        pg.wait_for_function("document.getElementById('mode').textContent.includes('감지 중')", timeout=3000)
        probe.subscribe(topic(device, "control"))
        probe.drain()
        probe.publish(topic(device, "status"), {"state": "idle", "fw": "0.1.0"}, retain=True)
        got = probe.next(topic(device, "control"), lambda m: m.get("cmd") == "start", timeout=3)
        assert got, "감지 중에 연 페이지가 재부팅 idle에 start를 다시 보내지 않음"
    finally:
        probe.stop()
        context.close()
        clear_retained(player, device)


@pytest.mark.feature("P11")
def test_no_resume_from_idle(page, cfg):
    """retain status가 idle이면(페이지만 연 상태) 시작 상태가 아니다."""
    pg, device = page
    connected(pg)
    probe = Probe(cfg["host"], cfg["mqtt_port"], "p11b")
    assert probe.start()
    probe.publish(topic(device, "status"), {"state": "idle", "fw": "0.1.0"}, retain=True)
    pg.wait_for_function("document.getElementById('esp32').textContent.includes('idle')", timeout=3000)
    probe.stop()
    assert pg.text_content("#mode") == "중지됨"
