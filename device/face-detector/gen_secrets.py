"""같은 폴더의 .env를 읽어 secrets.h를 만든다. 실행: python gen_secrets.py"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ["WIFI_SSID", "WIFI_PASSWORD", "BROKER_HOST", "BROKER_PORT", "DEVICE_ID"]
NUMBER_KEYS = {"BROKER_PORT"}


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def c_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_header(env: dict[str, str]) -> str:
    """env 값으로 secrets.h 내용을 만든다. 값이 빠졌거나 포트가 숫자가 아니면 ValueError."""
    missing = [k for k in KEYS if not env.get(k)]
    if missing:
        raise ValueError(f".env에 값이 없다: {', '.join(missing)}")
    if not env["BROKER_PORT"].isdigit():
        raise ValueError(f"BROKER_PORT는 숫자여야 한다: {env['BROKER_PORT']}")

    lines = [
        "// gen_secrets.py가 .env로 만든 파일. 직접 고치지 말고 .env를 고쳐 다시 만든다. 커밋하지 않는다.",
        "#pragma once",
        "",
    ]
    for key in KEYS:
        value = env[key] if key in NUMBER_KEYS else c_string(env[key])
        lines.append(f"#define {key:<13} {value}")
    return "\n".join(lines) + "\n"


def main() -> None:
    env_path = HERE / ".env"
    if not env_path.exists():
        sys.exit(f"{env_path}가 없다. .env.example을 .env로 복사해 채운다.")
    env = read_env(env_path)
    try:
        header = build_header(env)
    except ValueError as e:
        sys.exit(str(e))
    (HERE / "secrets.h").write_text(header, encoding="utf-8")
    print(f"secrets.h 생성: DEVICE_ID={env['DEVICE_ID']} BROKER={env['BROKER_HOST']}:{env['BROKER_PORT']} SSID={env['WIFI_SSID']}")


if __name__ == "__main__":
    main()
