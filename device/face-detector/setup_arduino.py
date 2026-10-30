"""업로드 전 준비를 한 번에 한다. 실행: python setup_arduino.py

1. sketch.yaml에 적힌 esp32 코어·라이브러리와 device/face-model/의 모델 라이브러리 zip을 Arduino IDE에 설치한다.
2. .env로 secrets.h를 만든다. .env가 없거나 값이 비어 있으면 무엇을 채울지 알려 준다.
3. ESP32가 USB로 연결됐는지, 어느 포트인지 알려 준다.

arduino-cli는 Arduino IDE 2에 들어 있는 것을 찾아 쓰고, IDE와 같은 설정 파일을 써서 IDE에 바로 설치된다.
못 찾으면 환경 변수 ARDUINO_CLI에 arduino-cli 경로를 넣는다.
"""

import json
import os
import re
import shutil
import subprocess
import zipfile
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI_IN_IDE = Path("resources/app/lib/backend/resources")
MODEL_DIR = HERE.parent / "face-model"  # Edge Impulse에서 내보낸 Arduino 라이브러리 zip을 face-model이 커밋하는 곳
ESPRESSIF_VID = "0x303a"  # XIAO ESP32S3는 칩 내장 USB라 Espressif VID로 잡힌다


def read_sketch_yaml(path: Path) -> dict:
    """sketch.yaml에서 플랫폼·보드 매니저 URL·라이브러리를 "이름@버전" 형태로 뽑는다 (PyYAML 없이)."""
    text = path.read_text(encoding="utf-8")
    platforms = [f"{n}@{v}" for n, v in re.findall(r"-\s*platform:\s*(\S+)\s*\(([^)]+)\)", text)]
    urls = re.findall(r"platform_index_url:\s*(\S+)", text)
    libs_block = re.search(r"libraries:\s*\n((?:\s+-.*\n?)+)", text)
    libraries = []
    if libs_block:
        libraries = [f"{n.strip()}@{v}" for n, v in re.findall(r"-\s*([^()\n]+?)\s*\(([^)]+)\)", libs_block.group(1))]
    return {"platforms": platforms, "urls": urls, "libraries": libraries}


def find_cli() -> str | None:
    if os.environ.get("ARDUINO_CLI"):
        return os.environ["ARDUINO_CLI"]
    if shutil.which("arduino-cli"):
        return "arduino-cli"
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Arduino IDE" / CLI_IN_IDE / "arduino-cli.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Arduino IDE" / CLI_IN_IDE / "arduino-cli.exe",
        Path("/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"),
    ]
    return next((str(p) for p in candidates if p.exists()), None)


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd[1:]), flush=True)
    if subprocess.run(cmd).returncode != 0:
        sys.exit(f"실패: {' '.join(cmd[1:])}")


def find_model_zips(model_dir: Path) -> list[Path]:
    """face-model이 커밋한 모델 라이브러리 zip들. 없으면 빈 목록."""
    return sorted(model_dir.glob("*.zip"))


def library_version(properties: str) -> str | None:
    m = re.search(r"^version=(.+)$", properties, re.M)
    return m.group(1).strip() if m else None


def install_library_zip(zip_path: Path, libraries_dir: Path) -> str:
    """Arduino 라이브러리 zip을 libraries 폴더에 푼다 (IDE의 Add .ZIP Library와 같은 일).
    같은 버전이 이미 있으면 그대로 두고, 다른 버전이면 그 라이브러리 폴더만 바꾼다. 설치한 "이름 버전"을 돌려준다."""
    with zipfile.ZipFile(zip_path) as z:
        props = [n for n in z.namelist() if re.fullmatch(r"[^/]+/library\.properties", n)]
        if len(props) != 1:
            raise ValueError(f"{zip_path.name}: Arduino 라이브러리 zip이 아닙니다 (최상위 폴더의 library.properties가 하나여야 함)")
        name = props[0].split("/")[0]
        version = library_version(z.read(props[0]).decode("utf-8", "replace"))
        target = libraries_dir / name
        installed = target / "library.properties"
        if installed.exists() and library_version(installed.read_text(encoding="utf-8", errors="replace")) == version:
            return f"{name} {version} (이미 설치됨)"
        if target.exists():
            shutil.rmtree(target)
        libraries_dir.mkdir(parents=True, exist_ok=True)
        z.extractall(libraries_dir, members=[n for n in z.namelist() if n.startswith(name + "/")])
    return f"{name} {version}"


def find_esp32_ports(board_list: dict) -> list[str]:
    """arduino-cli board list --format json 결과에서 ESP32(Espressif USB, VID 0x303A)가 꽂힌 포트를 찾는다."""
    ports = []
    for d in board_list.get("detected_ports", []):
        port = d.get("port", {})
        vid = port.get("properties", {}).get("vid", "").lower()
        boards = [b.get("fqbn", "") for b in d.get("matching_boards", [])]
        if vid == ESPRESSIF_VID or any(f.startswith("esp32:") for f in boards):
            ports.append(port.get("address", "?"))
    return ports


def fill_env_text(text: str, values: dict[str, str]) -> str:
    """.env 내용에서 values에 있는 키의 값만 바꾼다. 주석과 다른 줄은 그대로 둔다."""
    lines = []
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip()
        lines.append(f"{key}={values[key]}" if "=" in line and not line.lstrip().startswith("#") and key in values else line)
    return "\n".join(lines) + "\n"


def fill_env_from_this_pc() -> None:
    """.env가 없거나 Wi-Fi·broker 값이 비었으면 이 PC의 Wi-Fi 정보로 채울지 묻는다."""
    import detect_network
    import gen_secrets

    env_path, example_path = HERE / ".env", HERE / ".env.example"
    text = (env_path if env_path.exists() else example_path).read_text(encoding="utf-8")
    unfilled = gen_secrets.check_env(gen_secrets.read_env(env_path) if env_path.exists() else {}, gen_secrets.read_env(example_path))
    detected = detect_network.detect()
    found = {k: v for k, v in detected.items() if k in unfilled}
    if not found:
        return

    print("  이 PC의 Wi-Fi 정보로 .env를 채울 수 있습니다 (broker를 이 PC에서 띄우는 경우).")
    if found.get("WIFI_SSID") and found["WIFI_SSID"] != detected.get("PC_SSID"):
        print("  PC는 5G에 붙어 있어 같은 공유기의 2G SSID를 골랐습니다 (ESP32-S3는 2.4GHz만 됩니다).")
    for k, v in found.items():
        print(f"    {k}={detect_network.mask(v) if k == 'WIFI_PASSWORD' else v}")
    try:
        answer = input("  이 값으로 .env를 채울까요? [Y/n] ").strip().lower()
    except EOFError:  # 입력할 수 없는 환경(CI 등)
        answer = "n"
    if answer not in ("", "y", "yes"):
        print("  채우지 않았습니다.")
        return
    env_path.write_text(fill_env_text(text, found), encoding="utf-8")
    print(f"  {env_path}에 적었습니다.")


def main() -> None:
    cli = find_cli()
    if not cli:
        sys.exit("arduino-cli를 찾지 못했습니다. Arduino IDE 2를 설치하거나 환경 변수 ARDUINO_CLI에 arduino-cli 경로를 넣으세요.")

    base = [cli]
    ide_config = Path.home() / ".arduinoIDE" / "arduino-cli.yaml"
    if ide_config.exists():  # IDE와 같은 폴더에 설치되게 한다
        base += ["--config-file", str(ide_config)]

    print("[1/3] esp32 코어·라이브러리 설치")
    deps = read_sketch_yaml(HERE / "sketch.yaml")
    urls = [arg for u in deps["urls"] for arg in ("--additional-urls", u)]
    run(base + ["core", "update-index"] + urls)
    for p in deps["platforms"]:
        run(base + ["core", "install", p] + urls)
    run(base + ["lib", "install"] + deps["libraries"])
    zips = find_model_zips(MODEL_DIR)
    models = []
    if zips:
        # IDE와 같은 스케치북의 libraries 폴더에 푼다
        out = subprocess.run(base + ["config", "get", "directories.user"], capture_output=True, text=True)
        libraries_dir = Path(out.stdout.strip()) / "libraries"
        for z in zips:
            try:
                models.append(install_library_zip(z, libraries_dir))
            except (ValueError, zipfile.BadZipFile) as e:
                sys.exit(f"실패: {e}")
    print("  완료:", ", ".join(deps["platforms"] + deps["libraries"] + models))
    if not zips:
        print(f"  모델 zip이 아직 없습니다 ({MODEL_DIR}/*.zip). face-model이 올리면 다시 실행하세요.")

    print("[2/3] .env → secrets.h")
    import gen_secrets

    fill_env_from_this_pc()
    secrets_ok = True
    try:
        gen_secrets.main()
    except SystemExit as e:
        secrets_ok = False
        print(f"  {e}\n  채운 뒤 python gen_secrets.py를 실행하세요.")

    print("[3/3] 보드 연결")
    out = subprocess.run(base + ["board", "list", "--format", "json"], capture_output=True, text=True)
    ports = find_esp32_ports(json.loads(out.stdout or "{}")) if out.returncode == 0 else []
    if ports:
        print(f"  ESP32 연결됨: {', '.join(ports)}. Arduino IDE에서 이 포트를 고르고 업로드하세요.")
    else:
        print(
            "  ESP32가 연결되어 있지 않습니다. 보드를 USB로 꽂으세요.\n"
            "  꽂았는데도 안 보이면 충전 전용이 아닌 데이터 케이블인지 확인하고, BOOT 버튼을 누른 채로 다시 꽂으세요."
        )

    if not (secrets_ok and ports):
        sys.exit(1)


if __name__ == "__main__":
    main()
