from app import add


def test_add() -> None:
    assert add(2, 3) == 5, "Expected 5"
