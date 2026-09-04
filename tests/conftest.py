import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text("utf-8")


@pytest.fixture(autouse=True)
def _isolate_data(tmp_path, monkeypatch):
    """テストが本番の docs/data/ に書き込まないようにする。

    これが無いと `pytest` を一度走らせるだけで docs/data/health/t.json のような
    テスト由来のファイルが混ざり、ダッシュボードが「連続失敗中: t」と誤報を出す。
    実際に一度混入してコミットされた。
    """
    from collectors import common

    monkeypatch.setattr(common, "DATA", tmp_path / "data")
    yield
