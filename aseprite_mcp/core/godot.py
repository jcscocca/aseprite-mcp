"""Transform Aseprite's json-array spritesheet data into Godot-oriented metadata.

Godot import notes: with padding=0 and a uniform grid, `columns`/`rows` map to
Sprite2D hframes/vframes. The per-frame rects are always authoritative and can
drive AtlasTexture regions or a SpriteFrames resource; durations are in ms.
"""

from __future__ import annotations


def build_godot_metadata(ase_json: dict, texture: str) -> dict:
    frames_raw = ase_json.get("frames")
    if not isinstance(frames_raw, list) or not frames_raw:
        raise ValueError(
            "Aseprite spritesheet JSON has no frames array — export produced unusable metadata"
        )
    frames = []
    for i, f in enumerate(frames_raw):
        rect = f["frame"]
        frames.append(
            {
                "index": i,
                "x": rect["x"],
                "y": rect["y"],
                "w": rect["w"],
                "h": rect["h"],
                "duration_ms": f["duration"],
            }
        )
    first = frames[0]
    columns = sum(1 for f in frames if f["y"] == first["y"])
    rows = len({f["y"] for f in frames})

    tags = (ase_json.get("meta") or {}).get("frameTags") or []
    animations = []
    for tag in tags:
        indices = list(range(tag["from"], tag["to"] + 1))
        animations.append(
            {
                "name": tag["name"],
                "frames": indices,
                "durations_ms": [frames[i]["duration_ms"] for i in indices],
                "direction": tag.get("direction", "forward"),
            }
        )
    if not animations:
        animations.append(
            {
                "name": "default",
                "frames": [f["index"] for f in frames],
                "durations_ms": [f["duration_ms"] for f in frames],
                "direction": "forward",
            }
        )

    meta_size = (ase_json.get("meta") or {}).get("size") or {}
    return {
        "texture": texture,
        "sheet_width": meta_size.get("w"),
        "sheet_height": meta_size.get("h"),
        "frame_width": first["w"],
        "frame_height": first["h"],
        "frame_count": len(frames),
        "columns": columns,
        "rows": rows,
        "frames": frames,
        "animations": animations,
    }
