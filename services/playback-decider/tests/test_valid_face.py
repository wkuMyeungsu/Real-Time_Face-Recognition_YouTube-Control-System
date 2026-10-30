import pytest

from app.main import valid_face

GOOD = {"seq": 123, "face": True, "score": 0.91, "count": 1, "infer_ms": 95}


def test_contract_example_is_valid():
    assert valid_face(GOOD)
    assert valid_face({**GOOD, "face": False, "score": 0, "count": 0})


@pytest.mark.parametrize("change", [
    {"face": "yes"},
    {"face": 1},
    {"score": "0.9"},
    {"score": 1.5},
    {"score": -0.1},
    {"score": True},
    {"seq": -1},
    {"seq": 1.0},
    {"count": True},
    {"infer_ms": "95"},
])
def test_wrong_types_are_invalid(change):
    assert not valid_face({**GOOD, **change})


def test_missing_or_extra_field_is_invalid():
    missing = dict(GOOD)
    del missing["count"]
    assert not valid_face(missing)
    assert not valid_face({**GOOD, "extra": 1})
