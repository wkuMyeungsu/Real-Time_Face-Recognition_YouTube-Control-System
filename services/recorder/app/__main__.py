from .log_config import setup_logging

setup_logging()   # 진입점에서 한 번만 (LOG_ENV, LOG_TZ)

from .main import run  # noqa: E402

run()
