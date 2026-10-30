FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt

COPY pytest.ini ./
COPY app ./app
COPY tests ./tests

# 로그는 /app/logs에 쓴다. docker-compose.yml이 저장소의 ./logs를 여기에 붙인다
CMD ["python", "-m", "app"]
