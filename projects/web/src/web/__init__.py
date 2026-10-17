import os
from pathlib import Path

# dlt looks for .dlt/ (config.toml, secrets.toml) in the working directory unless DLT_PROJECT_DIR
# is set. Point it at this project, so pipelines run the same from the repo root, the project
# directory or a notebook. setdefault keeps an explicit DLT_PROJECT_DIR (e.g. in Docker) in charge.
PROJECT_DIR = Path(__file__).resolve().parents[2]

if (PROJECT_DIR / ".dlt").is_dir():
    os.environ.setdefault("DLT_PROJECT_DIR", str(PROJECT_DIR))
