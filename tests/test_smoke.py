from app.main import greet


def test_greet_returns_a_greeting():
    assert greet("world") == "hello, world"
