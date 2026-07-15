from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from akousmata_app.llm import LLMUnavailable, _cli, validate_http_url


def test_validate_http_url_rejects_local_file_and_embedded_credentials() -> None:
    with pytest.raises(ValueError):
        validate_http_url("file:///tmp/agent.sock")
    with pytest.raises(ValueError):
        validate_http_url("https://user:secret@example.test")


def test_cli_uses_argument_vector_without_a_shell() -> None:
    completed = Mock(returncode=0, stdout="heard", stderr="")
    with patch("subprocess.run", return_value=completed) as run:
        assert _cli("listen", {"command": "codex exec -"}, system=None, timeout=5) == "heard"
    run.assert_called_once_with(
        ["codex", "exec", "-"],
        input="listen",
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
    )


def test_cli_start_failure_is_reported_as_unavailable() -> None:
    with patch("subprocess.run", side_effect=OSError("missing executable")):
        with pytest.raises(LLMUnavailable, match="could not start"):
            _cli("listen", {"command": "missing-agent"}, system=None, timeout=5)
