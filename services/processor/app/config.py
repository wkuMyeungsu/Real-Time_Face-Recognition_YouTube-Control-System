import os

SERVICE_NAME = os.environ.get("SERVICE_NAME", "processor")
PORT = int(os.environ.get("PORT", "8001"))

# 컨테이너 안에서는 broker:1883. PC에서 직접 돌릴 때는 localhost.
BROKER_HOST = os.environ.get("BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("BROKER_PORT", "1883"))

# 판정 기준 (.env.example 참고)
PLAY_AFTER_MS = int(os.environ.get("PLAY_AFTER_MS", "500"))
PAUSE_AFTER_MS = int(os.environ.get("PAUSE_AFTER_MS", "1500"))
MIN_SCORE = float(os.environ.get("MIN_SCORE", "0.6"))
