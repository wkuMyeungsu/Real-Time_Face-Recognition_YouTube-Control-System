import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detect_network  # noqa: E402
import setup_arduino  # noqa: E402

PROFILES = """
Profiles on interface Wi-Fi:

User profiles
-------------
    All User Profile     : KT_GiGA_5G_Wave2_B36F
    All User Profile     : KT_GiGA_2G_Wave2_B36F
    All User Profile     : cafe wifi
"""


def test_field_reads_english_and_korean_labels():
    assert detect_network.field("    SSID                   : home 5G\n", "SSID") == "home 5G"
    assert detect_network.field("    키 콘텐츠            : secret pw\n", "Key Content", "키 콘텐츠") == "secret pw"
    assert detect_network.field("nothing here", "SSID") is None


def test_saved_profiles():
    assert detect_network.saved_profiles(PROFILES) == ["KT_GiGA_5G_Wave2_B36F", "KT_GiGA_2G_Wave2_B36F", "cafe wifi"]


def test_pick_2g_ssid_when_pc_is_on_5g():
    profiles = detect_network.saved_profiles(PROFILES)
    assert detect_network.pick_2g_ssid("KT_GiGA_5G_Wave2_B36F", profiles) == "KT_GiGA_2G_Wave2_B36F"


def test_pick_2g_ssid_keeps_ssid_without_saved_2g():
    assert detect_network.pick_2g_ssid("other_5G", ["other_5G"]) == "other_5G"
    assert detect_network.pick_2g_ssid("cafe wifi", ["cafe wifi"]) == "cafe wifi"


def test_mask_hides_password():
    assert detect_network.mask("password") == "pa******"


def test_fill_env_text_replaces_only_given_keys():
    text = "# 주석\nWIFI_SSID=wifi-name\nWIFI_PASSWORD=wifi-password\nDEVICE_ID=esp32-a\n"
    filled = setup_arduino.fill_env_text(text, {"WIFI_SSID": "home", "WIFI_PASSWORD": "p=w#1"})
    assert filled == "# 주석\nWIFI_SSID=home\nWIFI_PASSWORD=p=w#1\nDEVICE_ID=esp32-a\n"
