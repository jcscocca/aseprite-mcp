"""Unit tests for Godot metadata generation from Aseprite json-array data."""

from __future__ import annotations

import pytest

from aseprite_mcp.core.godot import build_godot_metadata


def _ase_json(n=3, w=16, h=16, tags=None):
    return {
        "frames": [
            {
                "filename": f"slime {i}.ase",
                "frame": {"x": i * w, "y": 0, "w": w, "h": h},
                "duration": 150,
            }
            for i in range(n)
        ],
        "meta": {"size": {"w": n * w, "h": h}, "frameTags": tags or []},
    }


def test_grid_and_frames():
    meta = build_godot_metadata(_ase_json(), "slime.png")
    assert meta["texture"] == "slime.png"
    assert meta["frame_count"] == 3
    assert meta["frame_width"] == 16
    assert (meta["columns"], meta["rows"]) == (3, 1)
    assert meta["sheet_width"] == 48
    assert meta["frames"][2] == {"index": 2, "x": 32, "y": 0, "w": 16, "h": 16, "duration_ms": 150}


def test_default_animation_when_untagged():
    meta = build_godot_metadata(_ase_json(), "s.png")
    assert meta["animations"] == [
        {"name": "default", "frames": [0, 1, 2], "durations_ms": [150, 150, 150], "direction": "forward"}
    ]


def test_frame_tags_become_animations():
    tags = [{"name": "idle", "from": 0, "to": 1, "direction": "pingpong"}]
    meta = build_godot_metadata(_ase_json(tags=tags), "s.png")
    assert meta["animations"] == [
        {"name": "idle", "frames": [0, 1], "durations_ms": [150, 150], "direction": "pingpong"}
    ]


def test_empty_frames_fails_loudly():
    with pytest.raises(ValueError, match="no frames"):
        build_godot_metadata({"frames": []}, "s.png")
