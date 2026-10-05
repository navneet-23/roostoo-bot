import json

import pytest

from bot.execution.rate_limiter import RateLimiter
from bot.execution.roostoo_client import RoostooClient, RoostooError, RoostooUnavailable, sign

SECRET = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"


def test_signing_matches_docs_example():
    params = {"pair": "BNB/USD", "quantity": "2000", "side": "BUY", "timestamp": "1580774512000", "type": "MARKET"}
    qs, sig = sign(params, SECRET)
    assert qs == "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
    assert sig == "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"


def test_signing_sorts_keys():
    qs, _ = sign({"type": "MARKET", "pair": "BTC/USD", "side": "SELL"}, SECRET)
    assert qs == "pair=BTC/USD&side=SELL&type=MARKET"


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, data, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "data": data})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_client(responses, limiter=None):
    t = FakeTransport(responses)
    lim = limiter or RateLimiter(100, 60)
    c = RoostooClient("KEY", SECRET, lim, transport=t, sleeper=lambda s: None)
    return c, t


def test_post_body_is_exact_signed_string_and_headers_set():
    c, t = make_client([(200, json.dumps({"Success": True, "OrderDetail": {"OrderID": 1}}))])
    c._ts = lambda: "1580774512000"
    c.place_order("BNB/USD", "BUY", "2000")
    call = t.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/v3/place_order")
    assert call["data"] == "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
    assert call["headers"]["RST-API-KEY"] == "KEY"
    assert call["headers"]["MSG-SIGNATURE"] == "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_get_signed_query_and_wallet_key_fallback():
    c, t = make_client([(200, json.dumps({"Success": True, "SpotWallet": {"USD": {"Free": 5}}}))])
    c._ts = lambda: "1700000000000"
    w = c.balance()
    assert w == {"USD": {"Free": 5}}
    assert t.calls[0]["url"].endswith("/v3/balance?timestamp=1700000000000")
    assert t.calls[0]["data"] is None
    assert "MSG-SIGNATURE" in t.calls[0]["headers"]


def test_public_ticker_has_timestamp_but_no_signature():
    c, t = make_client([(200, json.dumps({"Success": True, "Data": {"BTC/USD": {"MaxBid": 1}}}))])
    d = c.ticker("BTC/USD")
    assert d["BTC/USD"]["MaxBid"] == 1
    assert "timestamp=" in t.calls[0]["url"] and "pair=BTC/USD" in t.calls[0]["url"]
    assert "MSG-SIGNATURE" not in t.calls[0]["headers"]


def test_success_false_raises_and_is_not_retried():
    c, t = make_client([(200, json.dumps({"Success": False, "ErrMsg": "insufficient balance"}))])
    with pytest.raises(RoostooError, match="insufficient balance"):
        c.short_open("BTC/USD", "10")
    assert len(t.calls) == 1


def test_query_order_empty_result_is_empty_list():
    c, _ = make_client([(200, json.dumps({"Success": False, "ErrMsg": "no order matched"}))])
    assert c.query_order(pair="BTC/USD") == []


def test_retries_count_toward_rate_limit_and_backoff():
    lim = RateLimiter(100, 60)
    c, t = make_client([(500, "boom"), ConnectionError("down"), (200, json.dumps({"ServerTime": 7}))], lim)
    assert c.server_time() == 7
    assert len(t.calls) == 3
    assert lim.used() == 3


def test_unavailable_after_retries():
    c, t = make_client([(502, "x"), (502, "x"), (502, "x")])
    with pytest.raises(RoostooUnavailable):
        c.server_time()
    assert len(t.calls) == 3


def test_short_close_parameters():
    c, t = make_client([(200, json.dumps({"Success": True, "FullyClosed": True}))] * 3)
    c._ts = lambda: "1"
    c.short_close("BTC/USD")
    c.short_close("BTC/USD", close_qty="0.5")
    c.short_close("BTC/USD", close_pct="50")
    assert t.calls[0]["data"] == "pair=BTC/USD&timestamp=1"
    assert t.calls[1]["data"] == "close_qty=0.5&pair=BTC/USD&timestamp=1"
    assert t.calls[2]["data"] == "close_pct=50&pair=BTC/USD&timestamp=1"


def test_rate_limiter_blocks_at_limit():
    clock = {"t": 0.0}
    sleeps = []

    def sleeper(s):
        sleeps.append(s)
        clock["t"] += s

    lim = RateLimiter(3, 60, clock=lambda: clock["t"], sleeper=sleeper)
    for _ in range(3):
        lim.acquire()
    assert sleeps == []
    lim.acquire()                      # 4th call must wait until the first slot expires
    assert sleeps and clock["t"] >= 60
