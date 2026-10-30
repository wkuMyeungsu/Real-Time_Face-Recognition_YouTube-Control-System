"""계약 문서(docs/contracts)와 설정 파일끼리 맞는지 (C1~C7). 서비스 없이 돈다."""
import re
import tomllib

import jsonschema
import pytest

from contract_doc import examples, topic_table
from helpers import CONTRACTS, ROOT, TOPICS, schema, validate


@pytest.mark.feature("C1")
@pytest.mark.parametrize("kind", TOPICS)
def test_schema_is_valid(kind):
    jsonschema.Draft202012Validator.check_schema(schema(kind))


@pytest.mark.feature("C2")
def test_document_examples_match_schemas():
    found = examples()
    assert set(found) == set(TOPICS), f"예시가 없는 토픽: {set(TOPICS) - set(found)}"
    for kind, items in found.items():
        for item in items:
            validate(kind, item)


@pytest.mark.feature("C3")
@pytest.mark.parametrize("kind, payload", [
    ("control", {"cmd": "play"}),
    ("control", {}),
    ("face", {"seq": 1, "face": True, "score": 0.9}),                                  # count·infer_ms 없음
    ("face", {"seq": 1, "face": True, "score": 1.4, "count": 1, "infer_ms": 9}),      # 점수 범위 밖
    ("face", {"seq": 1, "face": "yes", "score": 0.9, "count": 1, "infer_ms": 9}),     # face가 참/거짓이 아님
    ("status", {"state": "running"}),                                                   # running·idle에는 fw가 있어야 함
    ("status", {"state": "sleeping", "fw": "0.1.0"}),
    ("playback", {"action": "stop"}),
    ("playback", {"action": "play", "extra": 1}),                                       # 문서에 없는 필드
])
def test_wrong_messages_are_rejected(kind, payload):
    with pytest.raises(jsonschema.ValidationError):
        validate(kind, payload)


@pytest.mark.feature("C4")
def test_topic_table_matches_schemas():
    table = topic_table()
    assert set(table) == set(TOPICS), f"문서 토픽 표: {sorted(table)}"
    assert {p.stem.split(".")[0] for p in (CONTRACTS / "schemas").glob("*.schema.json")} == set(TOPICS)
    assert table["status"]["retain"] and not table["face"]["retain"]  # 다른 테스트가 이 표를 기준으로 쓴다


@pytest.mark.feature("C5")
def test_esp32_environment_matches_ci():
    """환경 싱크: README '개발 환경' 표의 보드·코어·라이브러리 버전과 CI가 컴파일하는 버전이 같아야 한다."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    fqbn = re.search(r"FQBN `([^`]+)`", readme).group(1)
    core = re.search(r"\| esp32 코어 \| ([\d.]+)", readme).group(1)
    libs = dict(re.findall(r"(PubSubClient|ArduinoJson) ([\d.]+)", re.search(r"\| 라이브러리 \|([^\n]*)", readme).group(1)))
    assert f"fqbn: {fqbn}" in ci, f"CI의 FQBN이 README({fqbn})와 다름"
    assert re.search(rf"name: esp32:esp32\s+source-url: \S+\s+version: {re.escape(core)}\b", ci), f"CI의 esp32 코어가 README({core})와 다름"
    for name, version in libs.items():
        assert re.search(rf"name: {name}\s+version: {re.escape(version)}\b", ci), f"CI의 {name} 버전이 README({version})와 다름"
    cd = ROOT / ".github" / "workflows" / "cd.yml"
    if cd.is_file():  # 펌웨어 Release도 같은 환경으로 만든다
        text = cd.read_text(encoding="utf-8")
        assert fqbn in text and f"esp32:esp32@{core}" in text and all(f"{n}@{v}" in text for n, v in libs.items())


@pytest.mark.feature("C6")
def test_config_files_agree():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    defined = set(re.findall(r"^([A-Z_]+)=", env_example, re.M))
    used = set(re.findall(r"\$\{([A-Z_]+)", compose))
    assert used <= defined, f".env.example에 없는 변수: {used - defined}"
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for secret in (".env", "device/**/secrets.h", "services/broker/passwd"):
        assert secret in ignored, f".gitignore에 {secret}가 없음"


@pytest.mark.feature("C7")
def test_feature_registry_matches_tests():
    features = tomllib.loads((ROOT / "tests" / "features.toml").read_text(encoding="utf-8"))
    used = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        used |= set(re.findall(r'mark\.feature\("([A-Z]+\d+)"\)', path.read_text(encoding="utf-8")))
    assert used <= set(features), f"features.toml에 없는 기능: {used - set(features)}"
    assert set(features) <= used, f"테스트가 없는 기능: {set(features) - used}"
    for fid, f in features.items():
        assert f.get("status") in ("todo", "done") and f.get("part") and f.get("title"), f"{fid} 항목이 덜 채워짐"
