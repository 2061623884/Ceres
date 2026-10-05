"""V2 uses the checked-in supply, independent of the local source catalog."""

import pytest


@pytest.fixture()
def source_database_path(tmp_path):
    return tmp_path / "no-source.sqlite3"
