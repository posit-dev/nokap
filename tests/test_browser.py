import os
from unittest.mock import patch

from nokap._browser import find_chrome


def test_find_chrome_env_var(tmp_path):
    # Create a fake chrome binary
    fake_chrome = tmp_path / "chrome"
    fake_chrome.touch()

    with patch.dict(os.environ, {"CHROME_PATH": str(fake_chrome)}):
        result = find_chrome()
        assert result == str(fake_chrome)


def test_find_chrome_env_var_missing_file():
    with patch.dict(os.environ, {"CHROME_PATH": "/nonexistent/chrome"}):
        # Should fall through to platform search
        # May or may not find Chrome depending on system
        try:
            find_chrome()
        except RuntimeError as e:
            assert "Chrome/Chromium not found" in str(e)


def test_find_chrome_no_env_var():
    with patch.dict(os.environ, {}, clear=False):
        # Remove CHROME_PATH if set
        os.environ.pop("CHROME_PATH", None)
        # This may succeed or fail depending on whether Chrome is installed
        try:
            path = find_chrome()
            assert os.path.isfile(path)
        except RuntimeError:
            pass  # Chrome not installed, that's fine for CI
