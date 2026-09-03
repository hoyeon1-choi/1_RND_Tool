from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT_DIR / "tools"
TEMPLATE_DIR = TOOLS_DIR / "_template"


def ignore_generated_files(directory: str, names: list[str]) -> set[str]:
    """Skip runtime files when copying the template."""
    ignored = {name for name in names if name == "__pycache__" or name.endswith(".pyc")}

    if Path(directory).name in {"input", "output"}:
        ignored.update(name for name in names if name != ".gitkeep")

    return ignored


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a new tool from tools/_template.")
    parser.add_argument("tool_name", help="New tool folder name")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT_DIR))
    from common.utils import validate_tool_name

    try:
        tool_name = validate_tool_name(args.tool_name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    destination = TOOLS_DIR / tool_name
    if destination.exists():
        print(f"Tool already exists: {destination}", file=sys.stderr)
        return 1

    shutil.copytree(TEMPLATE_DIR, destination, ignore=ignore_generated_files)
    readme_path = destination / "README.md"
    main_path = destination / "main.py"

    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace("_template", tool_name),
        encoding="utf-8",
    )
    main_path.write_text(
        main_path.read_text(encoding="utf-8").replace("TOOL_NAME = \"_template\"", f"TOOL_NAME = \"{tool_name}\""),
        encoding="utf-8",
    )

    print(f"Created tool: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
