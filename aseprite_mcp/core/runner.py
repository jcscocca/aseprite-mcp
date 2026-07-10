"""Run generated Lua scripts through Aseprite in batch mode.

The binary is resolved from $ASEPRITE_BIN. In batch mode both print() output
and Lua error messages go to stdout, so failures are detected by exit code and
stdout is included verbatim in the raised error.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .lua import RESULT_MARKER

DEFAULT_ASEPRITE_BIN = "/Users/jscocca/Repos/aseprite/build/bin/aseprite"


class AsepriteError(RuntimeError):
    """Aseprite could not be launched, failed a script, or broke the result protocol."""


def aseprite_bin() -> str:
    return os.environ.get("ASEPRITE_BIN", DEFAULT_ASEPRITE_BIN)


def verify_binary() -> str:
    """Check the configured binary launches; return its version string."""
    bin_path = aseprite_bin()
    if not Path(bin_path).is_file():
        raise AsepriteError(
            f"Aseprite binary not found at {bin_path!r}. "
            "Set ASEPRITE_BIN to a working aseprite executable."
        )
    try:
        proc = subprocess.run(
            [bin_path, "--version"], capture_output=True, text=True, timeout=30
        )
    except OSError as e:
        raise AsepriteError(f"could not launch Aseprite at {bin_path!r}: {e}") from None
    version = proc.stdout.strip()
    if proc.returncode != 0 or not version.startswith("Aseprite"):
        raise AsepriteError(
            f"{bin_path!r} does not behave like Aseprite "
            f"(exit {proc.returncode}, output {version!r}). Check ASEPRITE_BIN."
        )
    return version


def run_script(lua_source: str, timeout: int = 120) -> str:
    """Execute a Lua script via `aseprite -b --script`; return stdout."""
    bin_path = aseprite_bin()
    script = tempfile.NamedTemporaryFile(
        mode="w", suffix=".lua", prefix="aseprite_mcp_", delete=False
    )
    try:
        script.write(lua_source)
        script.close()
        try:
            proc = subprocess.run(
                [bin_path, "-b", "--script", script.name],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except OSError as e:
            raise AsepriteError(
                f"could not launch Aseprite at {bin_path!r}: {e}. "
                "Set ASEPRITE_BIN to a working aseprite executable."
            ) from None
        except subprocess.TimeoutExpired:
            raise AsepriteError(
                f"Aseprite timed out after {timeout}s running script:\n{lua_source}"
            ) from None
        if proc.returncode != 0:
            raise AsepriteError(
                f"Aseprite script failed (exit {proc.returncode}).\n"
                f"--- output ---\n{proc.stdout.strip()}\n"
                f"--- stderr ---\n{proc.stderr.strip()}\n"
                f"--- script ---\n{lua_source}"
            )
        return proc.stdout
    finally:
        os.unlink(script.name)


def extract_result(stdout: str) -> dict:
    """Parse the last RESULT_MARKER line printed by a script."""
    result_line = None
    for line in stdout.splitlines():
        if line.startswith(RESULT_MARKER):
            result_line = line[len(RESULT_MARKER) :].strip()
    if result_line is None:
        raise AsepriteError(
            f"Aseprite script did not report a result ({RESULT_MARKER} line missing). "
            f"Output was:\n{stdout.strip()}"
        )
    try:
        return json.loads(result_line)
    except json.JSONDecodeError as e:
        raise AsepriteError(
            f"Aseprite script reported invalid JSON: {result_line!r} ({e})"
        ) from None
