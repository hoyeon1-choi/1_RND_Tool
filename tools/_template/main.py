from __future__ import annotations

from pathlib import Path

from common.logging import setup_logging
from common.paths import ensure_dir, tool_dir


TOOL_NAME = "_template"


def main() -> int:
    logger = setup_logging(TOOL_NAME)
    base_dir = tool_dir(TOOL_NAME)
    input_dir = ensure_dir(base_dir / "input")
    output_dir = ensure_dir(base_dir / "output")

    logger.info("Tool started")
    logger.info("Input folder: %s", input_dir)
    logger.info("Output folder: %s", output_dir)

    result_path = Path(output_dir) / "result.txt"
    result_path.write_text("Tool executed successfully.\n", encoding="utf-8")
    logger.info("Created: %s", result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

