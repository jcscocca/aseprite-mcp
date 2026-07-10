"""Deterministic core: op validation, Lua codegen, and the Aseprite subprocess runner.

Nothing in this package imports MCP. The LLM supplies the plan; this package
turns validated ops into Lua scripts and runs them through Aseprite in batch mode.
"""
