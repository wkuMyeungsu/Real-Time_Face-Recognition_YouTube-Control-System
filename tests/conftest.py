"""기능 목록(features.toml)으로 테스트를 묶고, 진행 상황을 요약한다 (docs/ci-cd.md).
서비스가 필요한 테스트는 docker compose up으로 띄운 것(localhost, .env 포트)을 쓴다.

- @pytest.mark.feature("P2"): 이 테스트는 기능 P2를 확인한다.
- 기능이 "todo"면 실패해도 통과로 친다 (xfail). 통과하면 실패로 친다 → features.toml에서 "done"으로 바꾸라는 뜻.
- 기능이 "done"이면 반드시 통과해야 한다.
- 서비스가 필요한 테스트(broker, playback-decider, player)는 서비스가 떠 있어야 한다. 로컬에서 안 떠 있으면 건너뛰고, CI에서는 실패로 친다.
"""
from __future__ import annotations

import os
import socket
import tomllib
from collections import defaultdict
from pathlib import Path

import pytest

from helpers import http_json, settings

FEATURES_PATH = Path(__file__).with_name("features.toml")
FEATURES: dict = tomllib.loads(FEATURES_PATH.read_text(encoding="utf-8"))
IN_CI = os.environ.get("CI") == "true"

# "todo" 기능에서 미구현으로 봐주는 실패: 기능이 동작하지 않아 생기는 실패만이다.
# 테스트 코드 자체의 실수(이름 오타, 없는 fixture, import 실패 등)는 봐주지 않고 오류로 드러낸다.
TODO_FAILURES: tuple = (AssertionError, TimeoutError, OSError, KeyError, TypeError)
try:
    from playwright.sync_api import Error as PlaywrightError  # 요소 없음, 기다림 시간 초과 등

    TODO_FAILURES += (PlaywrightError,)
except ImportError:
    pass

_item_feature: dict[str, str] = {}
_outcomes: dict[str, list[str]] = defaultdict(list)  # 기능 → 테스트 결과 목록


def pytest_configure(config):
    config.addinivalue_line("markers", "feature(id): tests/features.toml의 기능 번호")


def pytest_collection_modifyitems(config, items):
    for item in items:
        marker = item.get_closest_marker("feature")
        if marker is None:
            continue
        fid = marker.args[0]
        if fid not in FEATURES:
            raise pytest.UsageError(f"{item.nodeid}: tests/features.toml에 없는 기능 {fid!r}")
        _item_feature[item.nodeid] = fid
        feature = FEATURES[fid]
        if feature["status"] == "todo":
            item.add_marker(pytest.mark.xfail(
                strict=True, raises=TODO_FAILURES,
                reason=f"{fid} 아직 구현 전 ({feature['title']}). 통과하면 features.toml에서 \"done\"으로 바꾼다"))


def pytest_runtest_logreport(report):
    fid = _item_feature.get(report.nodeid)
    if fid is None:
        return
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        if hasattr(report, "wasxfail"):
            outcome = "xpassed" if report.outcome == "passed" else "xfailed"
        else:
            outcome = report.outcome
        _outcomes[fid].append(outcome)


def _feature_state(fid: str) -> str:
    results, status = _outcomes.get(fid, []), FEATURES[fid]["status"]
    if not results:
        return "–"
    if status == "done":
        return "✓ 통과" if all(r == "passed" for r in results) else ("건너뜀" if all(r == "skipped" for r in results) else "✗ 깨짐")
    if any(r == "failed" for r in results):  # strict xfail이 통과한 경우
        return "! 통과함 → done으로 바꾸기"
    return "건너뜀" if all(r == "skipped" for r in results) else "· 미구현"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    ran = [fid for fid in FEATURES if fid in _outcomes]
    if not ran:
        return
    by_part = defaultdict(list)
    for fid in ran:
        by_part[FEATURES[fid]["part"]].append(fid)
    tr = terminalreporter
    tr.section("기능 진행 상황 (tests/features.toml)")
    lines = ["| 파트 | 완료 | 기능 |", "|---|---|---|"]
    for part, fids in by_part.items():
        done = sum(FEATURES[f]["status"] == "done" for f in fids)
        tr.write_line(f"{part:10} 완료 {done}/{len(fids)}")
        detail = []
        for fid in fids:
            state = _feature_state(fid)
            tr.write_line(f"    {fid:4} {state:24} {FEATURES[fid]['title']}")
            detail.append(f"{fid} {state}")
        lines.append(f"| {part} | {done}/{len(fids)} | {'<br>'.join(detail)} |")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### 기능 진행 상황\n\n" + "\n".join(lines) + "\n\n")


# ── 서비스 확인 ──

def _need(name: str, ok: bool, how: str):
    if ok:
        return
    message = f"{name}에 접속할 수 없음. {how}"
    if IN_CI:
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="session")
def cfg():
    return settings()


@pytest.fixture(scope="session")
def broker(cfg):
    try:
        socket.create_connection((cfg["host"], cfg["mqtt_port"]), timeout=2).close()
        ok = True
    except OSError:
        ok = False
    _need("broker", ok, "docker compose up --build 먼저 띄운다")
    return cfg


def _health(url: str) -> bool:
    try:
        return http_json(url, timeout=3)[0] == 200
    except OSError:
        return False


@pytest.fixture(scope="session")
def browser():
    """웹 테스트용 크롬 (Playwright). 설치: pip install -r tools/requirements.txt && python -m playwright install chromium"""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="session")
def decider(broker):
    _need("playback-decider", _health(f"http://{broker['host']}:{broker['decider_port']}/health"), "docker compose up --build playback-decider")
    return broker


@pytest.fixture(scope="session")
def player(broker):
    _need("player", _health(f"http://{broker['host']}:{broker['player_port']}/health"), "docker compose up --build player")
    return broker
