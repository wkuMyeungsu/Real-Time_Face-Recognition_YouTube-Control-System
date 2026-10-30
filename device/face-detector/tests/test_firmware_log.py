"""펌웨어 로그가 팀 공통 형식(log.h)을 따르는지 소스만 보고 검사한다."""

import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SKETCH = (HERE / "face-detector.ino").read_text(encoding="utf-8")
LOG_H = (HERE / "log.h").read_text(encoding="utf-8")
MODULES = {"boot", "wifi", "mqtt", "camera", "infer"}


def test_sketch_logs_only_through_log_macros():
    """Serial.print를 직접 쓰면 형식이 흩어진다. 시리얼 출력은 log.h만 한다."""
    assert not re.search(r"Serial\.print", SKETCH)


def test_log_line_has_course_format_fields():
    """[up ms] levelname(8칸) zt.face-detector.<모듈> 파일:줄 메시지"""
    assert '"[up %lums] %-8s zt.face-detector.%s %s:%d %s\\n"' in LOG_H
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        assert f'"{level}"' in LOG_H


def test_log_modules_are_known():
    used = set(re.findall(r'\bLOG[DIWEC]\("([^"]+)"', SKETCH))
    assert used, "LOG 매크로를 하나도 쓰지 않음"
    assert used <= MODULES, f"모르는 모듈 이름: {used - MODULES} (loginfo 3-2의 이름 목록)"


def test_secrets_are_not_logged():
    assert not re.search(r"\bLOG[DIWEC]\([^;]*WIFI_PASSWORD", SKETCH)
