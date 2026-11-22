import pytest


@pytest.fixture(autouse=True)
def _clear_data_dir_cache():
    from ehr_media.config import get_data_dir

    get_data_dir.cache_clear()
    yield
    get_data_dir.cache_clear()