import re
import sys
import tomllib
from pathlib import Path


version = sys.argv[1]
if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.dev\d{8})?", version):
    raise SystemExit(f"Invalid distribution version: {version}")

path = Path("pyproject.toml")
text = path.read_text()
project = tomllib.loads(text)["project"]
dynamic = 'dynamic = ["version"]'
if project.get("dynamic") != ["version"] or text.count(dynamic) != 1:
    raise SystemExit("Expected a single dynamic project version")

path.write_text(text.replace(dynamic, f'version = "{version}"', 1))