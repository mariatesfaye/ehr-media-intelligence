import os
from pathlib import Path


def get_data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")).resolve()


def get_db_path() -> Path:
    return get_data_dir() / "ehr.db"