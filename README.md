# 1_RND_Tool

Workspace for small Python productivity tools.

## Layout

```text
1_RND_Tool/
├─ .venv/              # Shared Python 3.11.9 virtual environment
├─ common/             # Shared helper modules
├─ data/               # Shared data files
├─ docs/               # Notes and documents
├─ logs/               # Log files
├─ scripts/            # Project management scripts
└─ tools/              # One folder per tool
```

Each tool should live under `tools/<tool_name>/` and usually contain:

```text
tools/<tool_name>/
├─ README.md
├─ main.py
├─ config/
├─ input/
└─ output/
```

## First Use

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Check Python:

```powershell
python --version
```

Run the template tool:

```powershell
python .\scripts\run_tool.py _template
```

Create a new tool:

```powershell
python .\scripts\new_tool.py my_tool
```

Run the new tool:

```powershell
python .\scripts\run_tool.py my_tool
```

## Package Management

Install packages into the shared virtual environment:

```powershell
python -m pip install pandas openpyxl
python -m pip freeze > requirements.txt
```

Reinstall packages later:

```powershell
python -m pip install -r requirements.txt
```

