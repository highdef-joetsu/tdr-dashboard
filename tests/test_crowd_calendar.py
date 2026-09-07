from collectors.crowd_calendar import keep_forecast, parse_calendar

TODAY = "2026-09-07"


def test_future_day_keeps_tracking_the_forecast():
    # 未来日はまだ予想。日々の更新に追随する。
    prev = {"crowd_pct": 66, "forecast_pct": 66}
    assert keep_forecast(prev, {"crowd_pct": 64}, "2026-09-17", TODAY) == 64


def test_past_day_is_frozen_against_the_actual():
    # 日を過ぎると Queue-Times は実績値で上書きする。予想を残す。
    prev = {"crowd_pct": 62, "forecast_pct": 62}
    assert keep_forecast(prev, {"crowd_pct": 16}, "2026-09-06", TODAY) == 62


def test_today_freezes_this_mornings_forecast():
    # 当日は「その朝に見えていた予想」で凍結する。翌日の実績で動かさない。
    assert keep_forecast(None, {"crowd_pct": 64}, TODAY, TODAY) == 64
    prev = {"crowd_pct": 64, "forecast_pct": 64}
    assert keep_forecast(prev, {"crowd_pct": 20}, TODAY, "2026-09-08") == 64


def test_old_record_without_forecast_falls_back_to_its_own_value():
    assert keep_forecast({"crowd_pct": 54}, {"crowd_pct": 15}, "2026-09-06", TODAY) == 54


def test_parse_calendar_reads_pct_and_hours():
    html = '<a href="/parks/275/calendar/2026/09/17">17 61% 09:00 - 21:00</a>'
    assert parse_calendar(html) == {"2026-09-17": {"crowd_pct": 61, "hours": "09:00-21:00"}}
