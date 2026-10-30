import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setup_arduino  # noqa: E402

HERE = Path(setup_arduino.__file__).parent
ROOT = HERE.parents[1]
DEPS = setup_arduino.read_sketch_yaml(HERE / "sketch.yaml")


def test_read_sketch_yaml():
    assert DEPS["platforms"] == ["esp32:esp32@3.3.12"]
    assert DEPS["urls"] == ["https://espressif.github.io/arduino-esp32/package_esp32_index.json"]
    assert DEPS["libraries"] == ["PubSubClient@2.8", "ArduinoJson@7.2.1"]


def test_ci_uses_same_versions():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for dep in DEPS["platforms"] + DEPS["libraries"]:
        assert dep in ci, f"ci.yml에 {dep}가 없다. sketch.yaml과 버전을 맞춘다"


def test_readme_uses_same_versions():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for dep in DEPS["platforms"] + DEPS["libraries"]:
        version = dep.split("@")[1]
        assert version in readme, f"README에 {dep}의 버전 {version}이 없다. sketch.yaml과 버전을 맞춘다"


def test_find_esp32_ports():
    board_list = {
        "detected_ports": [
            {"port": {"address": "COM1", "properties": {}}},
            {"port": {"address": "COM7", "properties": {"vid": "0x303A", "pid": "0x1001"}}},
            {"port": {"address": "COM9", "properties": {}}, "matching_boards": [{"fqbn": "esp32:esp32:XIAO_ESP32S3"}]},
        ]
    }
    assert setup_arduino.find_esp32_ports(board_list) == ["COM7", "COM9"]


def test_find_esp32_ports_none_connected():
    assert setup_arduino.find_esp32_ports({"detected_ports": [{"port": {"address": "COM1", "properties": {}}}]}) == []
    assert setup_arduino.find_esp32_ports({}) == []
