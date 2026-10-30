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
