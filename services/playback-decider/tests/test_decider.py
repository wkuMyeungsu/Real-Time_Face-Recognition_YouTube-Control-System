import pytest

from app.decider import Decider


@pytest.fixture
def d():
    return Decider(play_after_ms=500, pause_after_ms=1500, min_score=0.6)


def feed(d, face, score, start_ms, end_ms, step_ms=200):
    """start_ms부터 end_ms까지 step_ms 간격으로 같은 face 메시지를 넣고, 나온 명령을 (시각, 명령)으로 모은다."""
    out = []
    for t in range(start_ms, end_ms + 1, step_ms):
        action = d.update(face, score, t)
        if action:
            out.append((t, action))
    return out


def test_play_after_face_continues(d):
    assert d.update(True, 0.9, 0) is None
    assert d.update(True, 0.9, 499) is None
    assert d.update(True, 0.9, 500) == "play"


def test_pause_after_face_gone(d):
    assert d.update(False, 0.0, 0) is None
    assert d.update(False, 0.0, 1499) is None
    assert d.update(False, 0.0, 1500) == "pause"


def test_same_action_only_once(d):
    assert feed(d, True, 0.9, 0, 3000) == [(600, "play")]
    assert feed(d, False, 0.0, 3200, 8000) == [(4800, "pause")]


def test_short_absence_does_not_pause(d):
    feed(d, True, 0.9, 0, 1000)
    assert feed(d, False, 0.0, 1200, 2600) == []  # 1.4초만 없음
    assert feed(d, True, 0.9, 2800, 5000) == []    # 이미 play라 다시 보내지 않음


def test_short_presence_does_not_play(d):
    feed(d, False, 0.0, 0, 2000)
    d.update(True, 0.9, 2200)
    d.update(True, 0.9, 2400)  # 0.2초만 보임
    assert d.update(False, 0.0, 2600) is None
    assert d.update(True, 0.9, 2800) is None  # 연속이 끊겼으니 처음부터
    assert d.update(True, 0.9, 3300) == "play"


def test_low_score_is_no_face(d):
    assert feed(d, True, 0.5, 0, 2000) == [(1600, "pause")]


def test_score_at_min_counts_as_face(d):
    assert feed(d, True, 0.6, 0, 600) == [(600, "play")]


def test_face_false_ignores_score(d):
    assert feed(d, False, 0.99, 0, 2000) == [(1600, "pause")]


def test_reset_forgets_last_action_and_streak(d):
    feed(d, True, 0.9, 0, 1000)
    d.reset()
    assert d.update(True, 0.9, 1200) is None  # 연속 시간도 처음부터
    assert d.update(True, 0.9, 1700) == "play"  # 마지막 명령을 잊었으니 다시 보냄


def test_zero_delay_acts_immediately():
    d = Decider(play_after_ms=0, pause_after_ms=0, min_score=0.6)
    assert d.update(True, 0.9, 0) == "play"
    assert d.update(False, 0.0, 100) == "pause"


# ---- tick(): face 메시지가 끊겨도 pause ----

@pytest.fixture
def started():
    d = Decider(play_after_ms=500, pause_after_ms=1500, min_score=0.6)
    d.reset(running=True, now_ms=0)
    return d


def test_tick_pauses_when_no_message_after_start(started):
    assert started.tick(1499) is None
    assert started.tick(1500) == "pause"
    assert started.tick(1600) is None  # 같은 명령은 한 번만


def test_tick_pauses_when_messages_stop(started):
    feed(started, True, 0.9, 0, 1000)  # 얼굴 있을 때만 보내다가 끊김
    assert started.tick(2499) is None
    assert started.tick(2500) == "pause"


def test_tick_pauses_after_last_no_face(started):
    feed(started, True, 0.9, 0, 1000)
    assert started.update(False, 0.0, 1200) is None  # 얼굴 없음 한 번 오고 끊김
    assert started.tick(2699) is None
    assert started.tick(2700) == "pause"


def test_tick_quiet_while_messages_come(started):
    for t in range(0, 5000, 200):
        started.update(True, 0.9, t)
        assert started.tick(t + 100) is None


def test_play_again_after_timeout_pause(started):
    feed(started, True, 0.9, 0, 1000)
    assert started.tick(2600) == "pause"
    assert started.update(True, 0.9, 5000) is None
    assert started.update(True, 0.9, 5500) == "play"


def test_tick_does_nothing_before_start(d):
    assert d.tick(10_000) is None


def test_tick_does_nothing_after_stop(started):
    feed(started, True, 0.9, 0, 1000)
    started.reset(running=False, now_ms=1100)
    assert started.tick(10_000) is None
