import uvicorn

from . import config
from .log_config import setup_logging

setup_logging()
# log_config=None: uvicorn이 자기 로그 설정으로 덮어쓰지 않게 한다 (/health 요청 로그가 다시 켜지지 않게)
uvicorn.run("app.main:app", host="0.0.0.0", port=config.PORT, log_config=None)
