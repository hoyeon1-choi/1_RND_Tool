from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT_DIR / "tools"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a tool from the tools directory.")
    parser.add_argument("tool_name", help="Tool folder name under tools/")
    parser.add_argument("tool_args", nargs=argparse.REMAINDER, help="Arguments passed to the tool")
    args = parser.parse_args()

    tool_main = TOOLS_DIR / args.tool_name / "main.py"
    if not tool_main.exists():
        print(f"Tool not found: {tool_main}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(ROOT_DIR))
    sys.argv = [str(tool_main), *args.tool_args]
    runpy.run_path(str(tool_main), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

