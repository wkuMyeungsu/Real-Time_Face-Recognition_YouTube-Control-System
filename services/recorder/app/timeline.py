"""logs/zt.log(사람이 읽는 한 타임라인)와 logs/zt.jsonl(분석용 원본)을 쓴다.

zt.log 한 줄은 공통 형식과 같고, 파일:줄 칸만 where로 바꿔 다른 파트가 보낸 위치를 그대로 쓴다.
    2026-10-30 14:05:07,502 INFO     zt.face-detector.wifi face-detector.ino:62 연결됨 device=esp32-a ip=… rssi_dbm=-48
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .log_config import ZtFormatter

LINE = "%(asctime)s %(levelname)-8s %(name)s %(where)s %(message)s"


class _Where(logging.Filter):
    """recorder 자신의 로그는 where = 파일:줄. 다른 파트에서 온 로그는 보낸 쪽의 where를 이미 갖고 있다."""

    def filter(self, record):
        if not hasattr(record, "where"):
            record.where = f"{record.filename}:{record.lineno}"
        return True


class Timeline:
    def __init__(self, directory, max_mb: float = 5, backups: int = 5, level: int = logging.INFO):
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        size = max(int(max_mb * 1024 * 1024), 1024)
        # 수업 2교시 STEP 06: RotatingFileHandler로 크기를 넘으면 zt.log.1, zt.log.2 … 로 돌린다
        self.handler = RotatingFileHandler(folder / "zt.log", maxBytes=size, backupCount=backups, encoding="utf-8")
        self.handler.setFormatter(ZtFormatter(LINE))
        self.handler.addFilter(_Where())
        self.handler.setLevel(level)
        self.raw_handler = RotatingFileHandler(folder / "zt.jsonl", maxBytes=size, backupCount=backups, encoding="utf-8")
        self.raw_handler.setFormatter(logging.Formatter("%(message)s"))
        self.path = folder / "zt.log"

    def attach(self, logger_name: str = "zt") -> None:
        """recorder 자신의 로그(zt.recorder.*, zt.broker)도 같은 타임라인에 쓴다."""
        logging.getLogger(logger_name).addHandler(self.handler)

    def foreign(self, level: int, logger: str, where: str, msg: str, t: float) -> None:
        """다른 파트(또는 mosquitto)가 남긴 로그 한 줄. t는 시각(Unix 초)."""
        if level < self.handler.level:
            return
        record = logging.LogRecord(logger, level, where, 0, msg, None, None)
        record.created, record.msecs, record.where = t, (t - int(t)) * 1000, where
        self.handler.handle(record)

    def raw(self, t: float, topic: str, payload, retain: bool, qos: int) -> None:
        """받은 메시지 원문 한 줄 (JSON Lines). face처럼 zt.log에 다 쓰지 않는 것도 여기에는 모두 남는다."""
        line = json.dumps({"t_ms": int(t * 1000), "topic": topic, "qos": qos, "retain": bool(retain), "payload": payload},
                          ensure_ascii=False, separators=(",", ":"))
        self.raw_handler.handle(logging.makeLogRecord({"msg": line}))

    def close(self) -> None:
        for h in (self.handler, self.raw_handler):
            logging.getLogger("zt").removeHandler(h)
            h.close()
