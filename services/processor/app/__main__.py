import logging

import uvicorn

from . import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
uvicorn.run("app.main:app", host="0.0.0.0", port=config.PORT)
