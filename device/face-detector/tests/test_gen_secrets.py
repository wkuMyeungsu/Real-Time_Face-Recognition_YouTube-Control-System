import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gen_secrets  # noqa: E402

VALID = {
    "WIFI_SSID": "my-wifi",
    "WIFI_PASSWORD": "pw",
    "BROKER_HOST": "192.168.0.12",
    "BROKER_PORT": "1883",
    "DEVICE_ID": "esp32-a",
}


def test_read_env_skips_comments_and_strips_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# 주석\n\nWIFI_SSID="my wifi"\nWIFI_PASSWORD=a=b\nDEVICE_ID = esp32-a \n', encoding="utf-8")
    assert gen_secrets.read_env(p) == {"WIFI_SSID": "my wifi", "WIFI_PASSWORD": "a=b", "DEVICE_ID": "esp32-a"}


def test_build_header_defines_all_keys():
    header = gen_secrets.build_header(VALID)
    assert '#define WIFI_SSID     "my-wifi"' in header
    assert "#define BROKER_PORT   1883" in header  # 숫자는 따옴표 없이
    assert '#define DEVICE_ID     "esp32-a"' in header


def test_build_header_escapes_quotes_and_backslashes():
    header = gen_secrets.build_header({**VALID, "WIFI_PASSWORD": 'a"b\\c'})
    assert '#define WIFI_PASSWORD "a\\"b\\\\c"' in header


def test_build_header_rejects_missing_value():
    with pytest.raises(ValueError, match="WIFI_PASSWORD"):
        gen_secrets.build_header({**VALID, "WIFI_PASSWORD": ""})


def test_build_header_rejects_non_numeric_port():
    with pytest.raises(ValueError, match="BROKER_PORT"):
        gen_secrets.build_header({**VALID, "BROKER_PORT": "abc"})


def test_env_example_has_every_key():
    env = gen_secrets.read_env(Path(gen_secrets.__file__).parent / ".env.example")
    gen_secrets.build_header(env)


def test_check_env_flags_empty_and_example_values():
    example = {"WIFI_SSID": "wifi-name", "WIFI_PASSWORD": "wifi-password", "BROKER_HOST": "192.168.0.99"}
    env = {**VALID, "WIFI_SSID": "", "WIFI_PASSWORD": "wifi-password"}
    assert gen_secrets.check_env(env, example) == ["WIFI_SSID", "WIFI_PASSWORD"]


def test_check_env_allows_default_port_and_device_id():
    assert gen_secrets.check_env(VALID, VALID) == ["WIFI_SSID", "WIFI_PASSWORD", "BROKER_HOST"]
    assert gen_secrets.check_env(VALID, {}) == []
