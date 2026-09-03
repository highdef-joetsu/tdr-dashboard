"""一過性の取得失敗と、コードの不具合を取り違えないこと。

取り違えると「ワークフローは緑なのにデータが増えない」状態になる。
"""
from collectors import common as c


def _raise(exc):
    def f():
        raise exc
    return f


def test_success_returns_zero():
    assert c.run("t", lambda: "ok") == 0


def test_transient_error_does_not_fail_the_job():
    assert c.run("t", _raise(c.TransientError("接続できない"))) == 0


def test_programming_error_fails_the_job():
    assert c.run("t", _raise(TypeError("bug"))) == 1


def test_config_error_fails_the_job():
    assert c.run("t", _raise(RuntimeError("環境変数が要る"))) == 1


def test_health_records_failure_either_way(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "DATA", tmp_path)
    c.run("x", _raise(c.TransientError("y")))
    h = c.read_health()
    assert h["x"]["consecutive_failures"] == 1
