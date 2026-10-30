"""face-detector·face-model (F1~F4, M1). 보드 없이 파일만 본다. 컴파일은 CI의 face-detector 잡."""
import re

import pytest

from helpers import ROOT

DETECTOR = ROOT / "device" / "face-detector"
REQUIRED = ["WIFI_SSID", "WIFI_PASSWORD", "BROKER_HOST", "BROKER_PORT", "DEVICE_ID"]


def sketch() -> str:
    return (DETECTOR / "face-detector.ino").read_text(encoding="utf-8")


@pytest.mark.feature("F1")
def test_secrets_example():
    text = (DETECTOR / "secrets.example.h").read_text(encoding="utf-8")
    missing = [n for n in REQUIRED if not re.search(rf"#define\s+{n}\b", text)]
    assert not missing, f"secrets.example.h에 없는 설정: {missing}"


@pytest.mark.feature("F2")
def test_prints_firmware_version_at_boot():
    """환경 싱크: 보드에 올라간 펌웨어 버전을 부팅할 때 찍는다 (README '실행 (ESP32)' 3번)."""
    src = sketch()
    assert re.search(r'#define\s+FW_VERSION\s+"[^"]+"', src)
    setup = src.split("void setup", 1)[1].split("void loop", 1)[0]
    assert "FW_VERSION" in setup, "setup()에서 FW_VERSION을 출력하지 않음"


@pytest.mark.feature("F3")
def test_topics_and_last_will_follow_contract():
    src = sketch()
    for kind in ("control", "face", "status"):
        assert f'"/{kind}"' in src, f"zt/<DEVICE_ID>/{kind} 토픽이 없음"
    lwt = re.search(r"mqtt\.connect\(\s*DEVICE_ID\s*,\s*topicStatus\.c_str\(\)\s*,\s*1\s*,\s*true\s*,\s*\"(.*?)\"\s*\)", src)
    assert lwt, "LWT를 status 토픽에 QoS 1, retain으로 걸지 않음"
    assert lwt.group(1).replace('\\"', '"') == '{"state":"offline"}'


@pytest.mark.feature("M1")
def test_edge_impulse_library():
    libs = [p for p in (ROOT / "device" / "face-model").rglob("library.properties") if p.parent.name.endswith("_inferencing")]
    assert libs, "device/face-model/<이름>_inferencing/library.properties가 없음 (Edge Impulse → Arduino library)"


@pytest.mark.feature("F4")
def test_logs_and_ping_pong():
    """LOG 매크로로 남기고 INFO 이상은 zt/<DEVICE_ID>/log/face-detector로 보낸다. ping은 받은 그대로 pong (docs/logging-design.txt 7-1)."""
    src = "\n".join(p.read_text(encoding="utf-8") for p in sorted(DETECTOR.glob("*")) if p.suffix in (".ino", ".h", ".cpp") and p.name != "secrets.h")
    assert re.search(r"#define\s+LOG[IWE]\b", src) and re.search(r"\bLOGI\s*\(", src), "LOGD·LOGI·LOGW·LOGE·LOGC 매크로가 없음"
    assert '"/log/face-detector"' in src, "zt/<DEVICE_ID>/log/face-detector 토픽이 없음"
    assert '"/ping"' in src and '"/pong"' in src, "ping을 받아 pong으로 돌려주지 않음"
