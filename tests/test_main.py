from bot.main import last_closed_bar_open_ms

H4 = 4 * 3600 * 1000


def test_last_closed_bar():
    # 2026-10-06 08:01 UTC -> last closed bar opened at 04:00 (closed at 08:00)
    now = 1791273660000
    assert last_closed_bar_open_ms(now) == 1791259200000
    assert last_closed_bar_open_ms(1791259200000 + H4 - 1) == 1791259200000 - H4
