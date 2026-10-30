"""face 메시지를 재생·정지 명령으로 바꾼다. ESP32 한 대당 Decider 하나."""

import logging

from . import config
from .mqtt_log import kv

log = logging.getLogger("zt.playback-decider.decider")


class Decider:
    def __init__(
        self,
        play_after_ms: int = config.PLAY_AFTER_MS,
        pause_after_ms: int = config.PAUSE_AFTER_MS,
        min_score: float = config.MIN_SCORE,
        device: str = "-",
    ):
        self.play_after_ms = play_after_ms
        self.pause_after_ms = pause_after_ms
        self.min_score = min_score
        self.device = device
        self.reset()

    def reset(self, running: bool = False, now_ms: int | None = None) -> None:
        """시작·중지 명령을 받았을 때 부른다. 마지막으로 보낸 명령을 잊는다.

        running: start면 True, stop이면 False. True일 때만 tick()이 메시지 끊김을 본다.
        """
        self.last_action: str | None = None
        # 얼굴 있음/없음이 이어지기 시작한 시각. 둘 중 하나만 값이 있다.
        self.present_since: int | None = None
        self.absent_since: int | None = None
        self.running = running
        # 마지막 face 메시지 시각. 시작 직후에는 시작 시각부터 센다.
        self.last_msg_ms: int | None = now_ms if running else None
        # 판정 로그에 남길 근거 face의 seq. 끊겨서 내린 판정은 마지막으로 받은 seq
        self.last_seq: int | None = None

    def update(self, face: bool, score: float, now_ms: int, seq: int | None = None) -> str | None:
        """face 메시지 하나를 넣으면 "play"·"pause"를 돌려준다. 보낼 명령이 없으면 None.

        - score < min_score이면 face가 true여도 얼굴 없음으로 본다.
        - 얼굴이 play_after_ms 이상 이어지면 "play", pause_after_ms 이상 없으면 "pause".
        - 같은 명령은 한 번만 돌려준다 (바뀔 때만).
        """
        self.last_msg_ms = now_ms
        self.last_seq = seq
        if face and score >= self.min_score:
            self.absent_since = None
            if self.present_since is None:
                self.present_since = now_ms
            present_ms = now_ms - self.present_since
            if present_ms >= self.play_after_ms:
                return self._emit("play", "face_present", "present_ms", present_ms)
        else:
            self.present_since = None
            if self.absent_since is None:
                self.absent_since = now_ms
            absent_ms = now_ms - self.absent_since
            if absent_ms >= self.pause_after_ms:
                return self._emit("pause", "face_absent", "absent_ms", absent_ms)
        return None

    def tick(self, now_ms: int) -> str | None:
        """메시지가 없어도 주기적으로 부른다. 돌려주는 값은 update()와 같다.

        - 시작 후 face 메시지가 pause_after_ms 동안 안 오면 그동안 얼굴이 없었던 것으로 보고 "pause".
          (face-detector가 얼굴 있을 때만 보내거나, 멈추거나, 연결이 끊긴 경우)
        - 얼굴 없음 메시지가 마지막이었다면 그 시각부터 pause_after_ms가 지나면 "pause".
        """
        if not self.running or self.last_msg_ms is None:
            return None
        silent_ms = now_ms - self.last_msg_ms
        if self.absent_since is None and silent_ms >= self.pause_after_ms:
            # 마지막 메시지 이후로 얼굴이 없었던 것으로 본다
            self.present_since = None
            self.absent_since = self.last_msg_ms
        if self.absent_since is None or now_ms - self.absent_since < self.pause_after_ms:
            return None
        if silent_ms >= self.pause_after_ms:
            return self._emit("pause", "face_timeout", "silent_ms", silent_ms)
        return self._emit("pause", "face_absent", "absent_ms", now_ms - self.absent_since)

    def _emit(self, action: str, reason: str, key: str, ms: int) -> str | None:
        if action == self.last_action:
            return None
        self.last_action = action
        kv(log, logging.INFO, f"{action} 판정", device=self.device, action=action, seq=self.last_seq, reason=reason,
           **{key: ms})
        return action
