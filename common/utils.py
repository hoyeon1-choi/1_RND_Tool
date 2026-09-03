from __future__ import annotations

import re


_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def validate_tool_name(name: str) -> str:
    """Validate a filesystem-friendly tool name."""
    if not _TOOL_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Tool name must start with a letter and contain only letters, numbers, "
            "hyphens, or underscores."
        )
    return name

