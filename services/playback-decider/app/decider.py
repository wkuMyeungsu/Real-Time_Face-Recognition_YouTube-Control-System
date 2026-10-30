"""face 메시지를 재생·정지 명령으로 바꾼다. ESP32 한 대당 Decider 하나."""

from . import config


class Decider:
    def __init__(
        self,
        play_after_ms: int = config.PLAY_AFTER_MS,
        pause_after_ms: int = config.PAUSE_AFTER_MS,
        min_score: float = config.MIN_SCORE,
    ):
        self.play_after_ms = play_after_ms
        self.pause_after_ms = pause_after_ms
        self.min_score = min_score
        self.reset()

    def reset(self) -> None:
        """시작·중지 명령을 받았을 때 부른다. 마지막으로 보낸 명령을 잊는다."""
        self.last_action: str | None = None

    def update(self, face: bool, score: float, now_ms: int) -> str | None:
        """face 메시지 하나를 넣으면 "play"·"pause"를 돌려준다. 보낼 명령이 없으면 None.

        - score < min_score이면 face가 true여도 얼굴 없음으로 본다.
        - 얼굴이 play_after_ms 이상 이어지면 "play", pause_after_ms 이상 없으면 "pause".
        - 같은 명령은 한 번만 돌려준다 (바뀔 때만).
        """
        # TODO(playback-decider): 위 규칙대로 구현하고 tests/test_decider.py에 경우별 테스트를 넣는다.
        return None
