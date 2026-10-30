"""recorder 설정. 모두 환경 변수로 바꿀 수 있고, 기본값만으로 docker compose에서 돈다."""
import os

SERVICE_NAME = os.environ.get("SERVICE_NAME", "recorder")
PORT = int(os.environ.get("PORT", "8002"))                    # /health (컨테이너 안 포트)
BROKER_HOST = os.environ.get("BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("BROKER_PORT", "1883"))      # 컨테이너끼리는 broker:1883 (호스트 포트 MQTT_PORT와 다름)

LOG_DIR = os.environ.get("LOG_DIR", "logs")                   # docker-compose.yml이 저장소의 ./logs를 /app/logs에 붙인다
LOG_MAX_MB = float(os.environ.get("LOG_MAX_MB", "5"))         # 파일 하나 최대 크기. 넘으면 zt.log.1 … 로 돌린다
LOG_BACKUPS = int(os.environ.get("LOG_BACKUPS", "5"))         # 남기는 이전 파일 수

FACE_SUMMARY_S = float(os.environ.get("FACE_SUMMARY_S", "5"))  # face는 원문 대신 이 간격으로 요약한다
PING_EVERY_S = float(os.environ.get("PING_EVERY_S", "30"))     # 기기마다 ping 간격
PONG_WAIT_S = float(os.environ.get("PONG_WAIT_S", "5"))        # 이 안에 pong이 없으면 못 받은 것으로 본다
SYS_SUMMARY_S = float(os.environ.get("SYS_SUMMARY_S", "60"))   # broker 통계·토픽별 메시지 수 요약 간격
FACE_MAX_PER_S = 10                                            # 계약: face는 초당 최대 10개
