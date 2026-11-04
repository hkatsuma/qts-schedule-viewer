import pytest


@pytest.fixture(autouse=True)
def isolated_annotation_database(tmp_path, monkeypatch):
    monkeypatch.setenv('QSV_DB_PATH', str(tmp_path / 'qsv.sqlite3'))
