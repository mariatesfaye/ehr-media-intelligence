import os
from functools import lru_cache
from pathlib import Path


@lru_cache
def get_data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")).resolve()


def get_db_path() -> Path:
    return get_data_dir() / "ehr.db"


def get_chroma_path() -> Path:
    return get_data_dir() / "chroma"