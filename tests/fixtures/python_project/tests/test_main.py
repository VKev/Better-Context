from ..src.utils.helpers import format_name


def test_format_name():
    assert format_name("world") == "Hello, world!"
