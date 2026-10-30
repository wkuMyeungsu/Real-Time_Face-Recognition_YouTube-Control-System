"""zero-touch-media 공통 로그 설정 (docs/logging-design.txt 3장, 수업 Day11 log_config.py 모양).

원본은 이 파일(common/log_config.py) 하나다. 도커 빌드가 서비스 폴더만 보므로, Python 서비스는
이 파일을 자기 app/log_config.py로 그대로 복사해 쓴다. 고칠 때는 원본을 고치고 복사본도 같이 바꾼다.
복사본이 원본과 같은지는 tests/test_contracts.py(C8)가 검사한다.

쓰는 법
    # 진입점(__main__.py)에서 한 번만. 핸들러는 여기 한 곳에만 붙는다
    from .log_config import setup_logging
    setup_logging()
    # 모듈에서는 이름만 나눠 쓴다: zt.<파트>.<모듈>
    log = logging.getLogger("zt.playback-decider.decider")
    log.info("play 판정 device=%s seq=%s reason=%s", device, seq, reason)   # f-string 대신 %s
    # uvicorn을 쓰면 uvicorn.run(..., log_config=None)으로 이 설정을 덮어쓰지 않게 한다

환경 변수 (.env)
    LOG_ENV  dev  : 콘솔에 DEBUG까지
             prod : 콘솔에 INFO 이상 (기본값). 파일로 모으는 일은 recorder가 한다
    LOG_TZ   시각을 찍을 시간대 (기본값 Asia/Seoul). 컨테이너 시계는 UTC라서 따로 정한다
"""
from __future__ import annotations

import logging
import logging.config
import os
from datetime import datetime

# 한 줄 모양: 시각(밀리초) 레벨(8칸) 로거 파일:줄 본문
FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(filename)s:%(lineno)d %(message)s"

# 라이브러리 로그는 WARNING 이상만 받는다 (수업 STEP 07 "잠재우기"). uvicorn.access는 /health 요청 로그
QUIET = ("paho.mqtt", "uvicorn.access", "urllib3", "asyncio")


def _zone(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # 시간대 정보(tzdata)가 없는 이미지면 컨테이너 시계 그대로 찍는다
        return None


class ZtFormatter(logging.Formatter):
    """asctime을 LOG_TZ 시간대로, 밀리초까지 찍는다 (2026-10-30 14:05:07,502)."""

    def __init__(self, fmt: str = FORMAT, tz: str | None = None):
        super().__init__(fmt)
        self.tz = _zone(tz or os.environ.get("LOG_TZ") or "Asia/Seoul")

    def formatTime(self, record, datefmt=None):
        if self.tz is None:
            return super().formatTime(record, datefmt)
        t = datetime.fromtimestamp(record.created, self.tz)
        return f"{t.strftime(datefmt or '%Y-%m-%d %H:%M:%S')},{int(record.msecs):03d}"


def log_env(env: str | None = None) -> str:
    return (env or os.environ.get("LOG_ENV") or "prod").strip().lower()


def build_config(env: str | None = None) -> dict:
    level = "DEBUG" if log_env(env) == "dev" else "INFO"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"line": {"()": ZtFormatter}},
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "line", "stream": "ext://sys.stdout"},
        },
        "loggers": {
            # 프로젝트 루트 로거. 핸들러는 여기 한 곳에만 붙이고 위로 올리지 않는다 (두 번 찍히지 않게)
            "zt": {"level": level, "handlers": ["console"], "propagate": False},
            **{name: {"level": "WARNING"} for name in QUIET},
        },
        "root": {"level": "WARNING", "handlers": ["console"]},
    }


def setup_logging(env: str | None = None) -> str:
    """진입점에서 한 번만 부른다. 적용한 zt 로거 레벨(DEBUG·INFO)을 돌려준다."""
    config = build_config(env)
    logging.config.dictConfig(config)
    return config["loggers"]["zt"]["level"]
