"""playback-decider (D1~D13). 기준: docs/contracts/README.md의 playback·log 절, .env.example의 판정 기준,
docs/logging-design.txt 7-3(판정 로그).

테스트마다 다른 기기(t-…)를 쓴다. playback-decider는 zt/+/…로 모든 기기를 받는다 (계약 '공통').
"""
import re
import time

import pytest

from contract_doc import topic_table
from helpers import ROOT, FaceFeeder, Probe, http_json, topic, unique_device, validate

SLACK = 1.5   # 판정이 늦게 와도 기다려 주는 여유 (초)
EARLY = 0.15  # 기준 시간보다 이만큼 일찍 와도 봐준다 (초, face 간격 0.1초)


class Board:
    """가짜 face-detector 한 대 + 그 기기의 playback을 받는 탐침."""

    def __init__(self, cfg, name):
        self.cfg, self.device = cfg, unique_device(name)
        self.t = {k: topic(self.device, k) for k in ("control", "face", "status", "playback")}
        self.probe = Probe(cfg["host"], cfg["mqtt_port"], name)
        assert self.probe.start(), self.probe.failed
        self.probe.subscribe(self.t["playback"])

    def control(self, cmd):
        self.probe.publish(self.t["control"], {"cmd": cmd}, qos=1)

    def playback(self, action, timeout):
        got = self.probe.next(self.t["playback"], lambda m: m.get("action") == action, timeout)
        if got:
            validate("playback", got[1])
        return got

    def quiet(self, seconds):
        got = self.probe.next(self.t["playback"], timeout=seconds)
        return got is None, (got[1] if got else None)

    def close(self):
        for k in ("control", "status", "playback"):
            self.probe.publish(self.t[k], b"", retain=True)
        self.probe.stop()


@pytest.fixture
def board(decider):
    made = []

    def make(name="d"):
        b = Board(decider, name)
        made.append(b)
        return b
    yield make
    for b in made:
        b.close()


def play_now(b, feeder, cfg):
    feeder.present = True
    got = b.playback("play", cfg["play_ms"] / 1000 + SLACK)
    assert got, "얼굴을 계속 보여 줬는데 play가 오지 않음"
    return got


@pytest.mark.feature("D1")
def test_health(decider):
    status, body = http_json(f"http://{decider['host']}:{decider['decider_port']}/health")
    assert status == 200 and body.get("ok") is True


@pytest.mark.feature("D2")
def test_stats(decider):
    status, body = http_json(f"http://{decider['host']}:{decider['decider_port']}/stats")
    assert status == 200 and isinstance(body, dict) and isinstance(body.get("devices"), dict)


@pytest.mark.feature("D3")
def test_play_after_face(board, cfg):
    b = board("d3")
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        play_now(b, f, cfg)


@pytest.mark.feature("D4")
def test_no_play_before_play_after_ms(board, cfg):
    b = board("d4")
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        time.sleep(0.4)  # 얼굴 없음부터
        b.probe.drain()
        f.present = True
        shown = time.monotonic()
        got = b.playback("play", cfg["play_ms"] / 1000 + SLACK)
    assert got, "play가 오지 않음"
    waited = got[0] - shown
    assert waited >= cfg["play_ms"] / 1000 - EARLY, f"PLAY_AFTER_MS({cfg['play_ms']}) 전에 재생 ({waited * 1000:.0f}ms)"


@pytest.mark.feature("D5")
def test_pause_after_face_gone(board, cfg):
    b = board("d5")
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        play_now(b, f, cfg)
        f.present = False
        hidden = time.monotonic()
        got = b.playback("pause", cfg["pause_ms"] / 1000 + SLACK)
    assert got, "얼굴을 숨겼는데 pause가 오지 않음"
    waited = got[0] - hidden
    assert waited >= cfg["pause_ms"] / 1000 - EARLY, f"PAUSE_AFTER_MS({cfg['pause_ms']}) 전에 정지 ({waited * 1000:.0f}ms)"


@pytest.mark.feature("D6")
def test_short_absence_does_not_pause(board, cfg):
    b = board("d6")
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        play_now(b, f, cfg)
        for _ in range(3):  # PAUSE_AFTER_MS의 1/3만 사라졌다 돌아옴
            f.present = False
            time.sleep(cfg["pause_ms"] / 3000)
            f.present = True
            time.sleep(0.4)
        quiet, got = b.quiet(1.0)
    assert quiet, f"잠깐 사라진 것으로 판정이 바뀜: {got}"


@pytest.mark.feature("D7")
def test_low_score_is_no_face(board, cfg):
    b = board("d7")
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        f.present, f.score = True, round(cfg["min_score"] - 0.1, 2)  # face는 true지만 점수가 MIN_SCORE보다 낮음
        assert not b.playback("play", cfg["play_ms"] / 1000 + SLACK), "MIN_SCORE보다 낮은데 play함"
        f.score = round(min(1.0, cfg["min_score"] + 0.2), 2)
        assert b.playback("play", cfg["play_ms"] / 1000 + SLACK), "점수를 올렸는데 play가 오지 않음"


@pytest.mark.feature("D8")
def test_sends_only_on_change(board, cfg):
    b = board("d8")
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        got = play_now(b, f, cfg)
        quiet, again = b.quiet(2.0)
        # retain 확인은 얼굴이 계속 들어오는 동안 한다. 얼굴을 멈추면 PAUSE_AFTER_MS 뒤 새 pause가 오는데,
        # 그 실시간 메시지를 retain으로 착각하지 않도록 받은 메시지의 retain 플래그를 본다
        late = Probe(cfg["host"], cfg["mqtt_port"], "d8-late")
        assert late.start()
        late.subscribe(b.t["playback"])
        kept = late.next(b.t["playback"], timeout=1.5)
        late.stop()
    assert quiet, f"같은 명령을 다시 보냄: {again}"
    rule = topic_table()["playback"]
    assert got[3] == rule["qos"], f"playback QoS가 문서({rule['qos']})와 다름: {got[3]}"
    retained = kept is not None and kept[2]
    assert retained == rule["retain"], f"playback retain이 문서와 다름 (늦게 구독한 쪽이 받은 것: {kept})"


@pytest.mark.feature("D9")
def test_control_resets_decision(board, cfg):
    """control을 받으면 판정을 처음으로 돌린다: 이미 play였어도 다시 play를 보낸다."""
    b = board("d9")
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        play_now(b, f, cfg)
        b.control("start")  # 시작 버튼을 다시 누름
        assert b.playback("play", cfg["play_ms"] / 1000 + SLACK), "control 뒤에 판정이 처음부터 다시 되지 않음"


@pytest.mark.feature("D10")
def test_devices_are_separate(board, cfg):
    a, c = board("d10a"), board("d10b")
    a.control("start")
    c.control("start")
    with FaceFeeder(a.probe, a.device) as fa, FaceFeeder(c.probe, c.device) as fc:
        fc.present = False
        play_now(a, fa, cfg)
        assert not c.playback("play", 1.0), "다른 기기 얼굴로 판정함"


@pytest.mark.feature("D11")
def test_bad_messages_are_dropped(board, cfg):
    url = f"http://{cfg['host']}:{cfg['decider_port']}/stats"
    _, before = http_json(url)
    b = board("d11")
    for payload in (b"not json", b"[1, 2]", {"seq": 1}, {"face": "maybe", "score": "high"}):
        b.probe.publish(b.t["face"], payload, qos=0)
    time.sleep(0.5)
    status, after = http_json(url)
    assert status == 200, "형식이 틀린 메시지를 받고 멈춤"
    assert after["bad_msgs"] >= before["bad_msgs"] + 3


def _fields(m):
    return m.get("fields") or {}


@pytest.mark.feature("D12")
def test_decision_is_logged_with_reason(board, cfg):
    """판정을 zt/<기기>/log/playback-decider로 남긴다: action과 reason(face_present·face_absent·face_timeout) (docs/logging-design.txt 7-3)."""
    b = board("d12")
    t = f"zt/{b.device}/log/playback-decider"
    logs = Probe(cfg["host"], cfg["mqtt_port"], "d12-log")
    assert logs.start()
    logs.subscribe(t)
    b.control("start")
    with FaceFeeder(b.probe, b.device) as f:
        play_now(b, f, cfg)
        played = logs.expect(t, lambda m: _fields(m).get("action") == "play", timeout=2)
        f.present = False   # 얼굴 없음이 PAUSE_AFTER_MS 이어지면 pause
        paused = logs.expect(t, lambda m: _fields(m).get("action") == "pause", timeout=cfg["pause_ms"] / 1000 + SLACK)
    logs.stop()
    assert played, "play 판정 로그가 log 토픽에 없음"
    validate("log", played)
    assert played["logger"].startswith("zt.playback-decider") and _fields(played).get("reason") == "face_present"
    assert paused and _fields(paused).get("reason") == "face_absent", "pause 판정 로그(reason=face_absent)가 없음"


@pytest.mark.feature("D13")
def test_uses_common_log_config():
    """공통 로그 설정을 쓴다: app/log_config.py(원본 그대로, C8), 진입점에서 setup_logging, uvicorn이 덮어쓰지 않게 log_config=None."""
    app = ROOT / "services" / "playback-decider" / "app"
    assert (app / "log_config.py").is_file(), "app/log_config.py가 없음 (common/log_config.py를 복사)"
    main = (app / "__main__.py").read_text(encoding="utf-8")
    assert "setup_logging(" in main and "basicConfig" not in main, "__main__.py가 basicConfig 대신 setup_logging()을 쓰지 않음"
    assert re.search(r"uvicorn\.run\([^)]*log_config\s*=\s*None", main), "uvicorn.run(..., log_config=None)이 아님 (/health 요청 로그가 다시 켜짐)"
