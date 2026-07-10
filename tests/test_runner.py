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


def test_extract_result_bad_json_fails_loudly():
    with pytest.raises(runner.AsepriteError, match="invalid JSON"):
        runner.extract_result("AMCP_RESULT {broken\n")


def test_verify_binary_missing_path_raises(monkeypatch):
    monkeypatch.setenv("ASEPRITE_BIN", "/definitely/not/here")
    with pytest.raises(runner.AsepriteError, match="ASEPRITE_BIN"):
        runner.verify_binary()


def test_run_script_reports_script_and_output_on_failure(monkeypatch, tmp_path):
    fake = tmp_path / "fake-aseprite"
    fake.write_text("#!/bin/sh\necho 'boom: something broke'\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ASEPRITE_BIN", str(fake))
    with pytest.raises(runner.AsepriteError) as exc:
        runner.run_script("error('x')")
    msg = str(exc.value)
    assert "boom: something broke" in msg  # aseprite errors land on stdout
    assert "error('x')" in msg  # generated script included for debuggability


def test_run_script_returns_stdout(monkeypatch, tmp_path):
    fake = tmp_path / "fake-aseprite"
    fake.write_text("#!/bin/sh\necho 'AMCP_RESULT {\"ok\": true}'\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ASEPRITE_BIN", str(fake))
    out = runner.run_script("print('hi')")
    assert runner.extract_result(out) == {"ok": True}
