from fastapi.testclient import TestClient

from app.main import app


def test_health():
    # with 없이 쓰면 lifespan(broker 연결)을 건너뛴다
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True
