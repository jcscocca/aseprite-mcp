"""Unit tests for the subprocess runner plumbing — no binary needed."""

from __future__ import annotations

import pytest

from aseprite_mcp.core import runner


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("ASEPRITE_BIN", "/custom/aseprite")
    assert runner.aseprite_bin() == "/custom/aseprite"


def test_default_bin_used_when_env_unset(monkeypatch):
    monkeypatch.delenv("ASEPRITE_BIN", raising=False)
    assert runner.aseprite_bin() == runner.DEFAULT_ASEPRITE_BIN


def test_extract_result_parses_marker_line():
    stdout = "noise\nAMCP_RESULT {\"width\": 16}\ntrailing\n"
    assert runner.extract_result(stdout) == {"width": 16}


def test_extract_result_uses_last_marker():
    stdout = 'AMCP_RESULT {"n": 1}\nAMCP_RESULT {"n": 2}\n'
    assert runner.extract_result(stdout) == {"n": 2}


def test_extract_result_missing_marker_fails_loudly():
    with pytest.raises(runner.AsepriteError, match="did not report a result"):
        runner.extract_result("just noise\n")


def test_extract_result_optional_returns_none_without_marker():
    assert runner.extract_result_optional("just noise\n") is None


def test_extract_result_optional_parses_marker():
    assert runner.extract_result_optional('AMCP_RESULT {"a": 1}\n') == {"a": 1}


def test_extract_result_optional_still_rejects_bad_json():
    with pytest.raises(runner.AsepriteError, match="invalid JSON"):
        runner.extract_result_optional("AMCP_RESULT {broken\n")


def test_extract_result_bad_json_fails_loudly():
    with pytest.raises(runner.AsepriteError, match="invalid JSON"):
        runner.extract_result("AMCP_RESULT {broken\n")


def test_verify_binary_missing_path_raises(monkeypatch):
    monkeypatch.setenv("ASEPRITE_BIN", "/definitely/not/here")
    with pytest.raises(runner.AsepriteError, match="ASEPRITE_BIN"):
        runner.verify_binary()


def test_run_script_failure_reports_output_without_script(monkeypatch, tmp_path):
    fake = tmp_path / "fake-aseprite"
    fake.write_text("#!/bin/sh\necho 'boom: something broke'\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ASEPRITE_BIN", str(fake))
    monkeypatch.delenv("ASEPRITE_MCP_DEBUG", raising=False)
    with pytest.raises(runner.AsepriteError) as exc:
        runner.run_script("error('x')")
    msg = str(exc.value)
    assert "boom: something broke" in msg  # aseprite errors land on stdout
    assert "error('x')" not in msg  # script dump is debug-only noise for agents
    assert "ASEPRITE_MCP_DEBUG" in msg  # points at the flag that restores it


def test_run_script_failure_includes_script_when_debug_set(monkeypatch, tmp_path):
    fake = tmp_path / "fake-aseprite"
    fake.write_text("#!/bin/sh\necho 'boom'\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ASEPRITE_BIN", str(fake))
    monkeypatch.setenv("ASEPRITE_MCP_DEBUG", "1")
    with pytest.raises(runner.AsepriteError) as exc:
        runner.run_script("error('x')")
    assert "error('x')" in str(exc.value)


def test_run_script_timeout_omits_script_by_default(monkeypatch, tmp_path):
    fake = tmp_path / "fake-aseprite"
    fake.write_text("#!/bin/sh\nsleep 5\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ASEPRITE_BIN", str(fake))
    monkeypatch.delenv("ASEPRITE_MCP_DEBUG", raising=False)
    with pytest.raises(runner.AsepriteError) as exc:
        runner.run_script("error('x')", timeout=1)
    msg = str(exc.value)
    assert "timed out" in msg
    assert "error('x')" not in msg


def test_run_script_returns_stdout(monkeypatch, tmp_path):
    fake = tmp_path / "fake-aseprite"
    fake.write_text("#!/bin/sh\necho 'AMCP_RESULT {\"ok\": true}'\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ASEPRITE_BIN", str(fake))
    out = runner.run_script("print('hi')")
    assert runner.extract_result(out) == {"ok": True}
