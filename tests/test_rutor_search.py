from backend.infrastructure.search.rutor import _parse_size_bytes


def test_parse_rutor_human_readable_size() -> None:
    assert _parse_size_bytes("1.5 GB") == int(1.5 * 1024**3)
    assert _parse_size_bytes("700 МБ") == 700 * 1024**2


def test_parse_rutor_numeric_size() -> None:
    assert _parse_size_bytes("1048576") == 1048576
    assert _parse_size_bytes(None) is None
