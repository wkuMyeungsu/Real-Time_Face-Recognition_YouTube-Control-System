"""이 PC가 붙은 Wi-Fi의 SSID·비밀번호와 Wi-Fi IP를 찾아 .env 값으로 돌려준다 (Windows, netsh).

broker를 이 PC에서 띄우고 ESP32도 이 PC의 Wi-Fi에 붙인다는 전제다. 서버를 다른 PC에서 띄우면 쓰지 않는다.
ESP32-S3는 2.4GHz만 되므로 PC가 5G에 붙어 있으면 같은 공유기의 2G SSID(이름의 5G → 2G)를 고른다.
실행: python detect_network.py (비밀번호는 가려서 보여 준다)
"""

import re
import subprocess
import sys


def netsh(*args: str) -> str:
    out = subprocess.run(["netsh", *args], capture_output=True, text=True, errors="replace")
    return out.stdout if out.returncode == 0 else ""


def field(text: str, *labels: str) -> str | None:
    """netsh 출력에서 "라벨 : 값"의 값을 찾는다. 영어·한국어 라벨을 함께 받는다."""
    for label in labels:
        m = re.search(rf"^\s*{label}\s*:\s*(.+?)\s*$", text, re.M)
        if m:
            return m.group(1)
    return None


def saved_profiles(profiles_text: str) -> list[str]:
    return [
        m.group(1)
        for line in profiles_text.splitlines()
        if ("Profile" in line or "프로필" in line) and (m := re.search(r":\s*(.+?)\s*$", line))
    ]


def pick_2g_ssid(ssid: str, profiles: list[str]) -> str:
    """5G SSID면 저장된 프로필 중 같은 이름의 2G SSID를 고른다. 없으면 그대로."""
    for a, b in (("5G", "2G"), ("5g", "2g"), ("_5", "_2")):
        candidate = ssid.replace(a, b)
        if a in ssid and candidate in profiles:
            return candidate
    return ssid


def detect() -> dict[str, str]:
    """찾은 값만 담아 돌려준다. 키: WIFI_SSID, WIFI_PASSWORD, BROKER_HOST, 그리고 참고용 PC_SSID."""
    if sys.platform != "win32":
        return {}
    found = {}
    iface = netsh("wlan", "show", "interfaces")
    ssid = field(iface, "SSID")
    if ssid:
        found["PC_SSID"] = ssid
        target = pick_2g_ssid(ssid, saved_profiles(netsh("wlan", "show", "profiles")))
        found["WIFI_SSID"] = target
        password = field(netsh("wlan", "show", "profile", f"name={target}", "key=clear"), "Key Content", "키 콘텐츠")
        if password:
            found["WIFI_PASSWORD"] = password
    name = field(iface, "Name", "이름")
    if name:
        ip = field(netsh("interface", "ipv4", "show", "addresses", f"name={name}"), "IP Address", "IP 주소")
        if ip:
            found["BROKER_HOST"] = ip
    return found


def mask(value: str) -> str:
    return value[:2] + "*" * max(len(value) - 2, 0)


if __name__ == "__main__":
    values = detect()
    if not values:
        sys.exit("찾지 못했습니다. Windows에서 Wi-Fi에 붙어 있는지 확인하세요. 아니면 .env에 직접 적으세요.")
    for k, v in values.items():
        print(f"{k}={mask(v) if k == 'WIFI_PASSWORD' else v}")
