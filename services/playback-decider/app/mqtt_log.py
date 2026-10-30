"""로그를 콘솔 한 줄(key=value)과 MQTT log 토픽(docs/contracts의 log) 양쪽으로 남긴다.

    kv(log, logging.INFO, "play 판정", device="esp32-a", seq=12, reason="face_present")
    → 콘솔: ... play 판정 device=esp32-a seq=12 reason=face_present
    → zt/esp32-a/log/playback-decider: {"level": "INFO", "msg": "play 판정", "fields": {...}, ...}

공통 설정(log_config.py)은 원본 그대로 써야 해서, MQTT 핸들러는 여기서 zt.playback-decider 로거에만 붙인다.
"""

import json
import logging

PART = "playback-decider"


def kv(logger: logging.Logger, level: int, msg: str, device: str | None = None, exc_info=False, **fields) -> None:
    if device is not None:
        fields = {"device": device, **fields}
    text = " ".join([msg, *(f"{k}={v}" for k, v in fields.items())])
    # stacklevel=2: 파일:줄 칸에 kv()가 아니라 부른 곳이 찍히게
    logger.log(level, "%s", text, exc_info=exc_info, stacklevel=2,
               extra={"zt_msg": msg, "zt_device": device, "zt_fields": fields})


def _value(v):
    return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)


class MqttLogHandler(logging.Handler):
    """INFO 이상을 zt/<기기>/log/playback-decider로 보낸다 (QoS 0). 기기와 상관없는 로그는 <기기> 자리에 server."""

    def __init__(self, client):
        super().__init__(logging.INFO)
        self.client = client

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not self.client.is_connected():
                return
            body = {
                "level": record.levelname,
                "logger": record.name,
                "where": f"{record.filename}:{record.lineno}",
                "msg": getattr(record, "zt_msg", None) or record.getMessage(),
                "ts_ms": int(record.created * 1000),
            }
            fields = getattr(record, "zt_fields", None)
            if fields:
                body["fields"] = {k: _value(v) for k, v in fields.items()}
            device = getattr(record, "zt_device", None) or "server"
            self.client.publish(f"zt/{device}/log/{PART}", json.dumps(body, ensure_ascii=False), qos=0)
        except Exception:
            self.handleError(record)
