from pathlib import Path

from gun._utils import current_platform, file_url, find_open_port, is_url


def test_file_url_absolute_path():
    p = Path("/tmp/test.html")
    result = file_url(p)
    assert result.startswith("file://")
    assert "test.html" in result


def test_file_url_with_spaces():
    p = Path("/tmp/my file.html")
    result = file_url(p)
    assert "my%20file.html" in result


def test_is_url_http():
    assert is_url("http://example.com")
    assert is_url("https://example.com")
    assert is_url("file:///tmp/test.html")


def test_is_url_not_url():
    assert not is_url("/tmp/test.html")
    assert not is_url("test.html")
    assert not is_url("C:\\Users\\test.html")


def test_find_open_port():
    port = find_open_port()
    assert 1024 <= port <= 65535


def test_current_platform():
    plat = current_platform()
    assert plat in ("macos", "linux", "windows")
