"""smoke test (E1, E2): 통합 뒤 전체가 이어지는지 (docs/ci-setup-guide.txt "나중에 더할 것").

E1: 가짜 face-detector로 control start → face → zt/<기기>/playback play → 얼굴 없음 → pause
E2: 브라우저로 player의 시작 버튼부터 유튜브 재생·정지까지
"""
import pytest

from helpers import FaceFeeder, Probe, clear_retained, open_player, topic, unique_device


@pytest.mark.feature("E1")
def test_start_face_playback(decider, cfg):
    device = unique_device("e1")
    probe = Probe(cfg["host"], cfg["mqtt_port"], "e1")
    assert probe.start()
    probe.subscribe(topic(device, "playback"))
    try:
        probe.publish(topic(device, "control"), {"cmd": "start"})
        with FaceFeeder(probe, device) as f:
            f.present = True
            assert probe.expect(topic(device, "playback"), lambda m: m.get("action") == "play", cfg["play_ms"] / 1000 + 2), "play가 오지 않음"
            f.present = False
            assert probe.expect(topic(device, "playback"), lambda m: m.get("action") == "pause", cfg["pause_ms"] / 1000 + 2), "pause가 오지 않음"
    finally:
        probe.stop()
        clear_retained(cfg, device)


@pytest.mark.feature("E2")
def test_player_button_to_youtube(decider, player, browser, cfg):
    device = unique_device("e2")
    context, pg = open_player(browser, cfg, device)
    board = Probe(cfg["host"], cfg["mqtt_port"], "e2-board")
    assert board.start()
    board.subscribe(topic(device, "control"))  # 진짜 face-detector처럼 start를 기다린다
    try:
        pg.wait_for_function("document.getElementById('broker').textContent.includes('연결됨')", timeout=8000)
        pg.wait_for_function("(window.__yt || []).some((c) => c[0] === 'new')", timeout=5000)
        pg.click("#start")
        assert board.expect(topic(device, "control"), lambda m: m.get("cmd") == "start", 3), "시작 버튼의 control이 오지 않음"
        with FaceFeeder(board, device) as f:
            f.present = True
            pg.wait_for_function("(window.__yt || []).some((c) => c[0] === 'playVideo')", timeout=cfg["play_ms"] + 3000)
            f.present = False
            pg.wait_for_function("(window.__yt || []).some((c) => c[0] === 'pauseVideo')", timeout=cfg["pause_ms"] + 3000)
    finally:
        board.stop()
        context.close()
        clear_retained(cfg, device)
