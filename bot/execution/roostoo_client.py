"""Roostoo REST client (https://github.com/roostoo/Roostoo-API-Documents).

Signing (RCL_TopLevelCheck): sort the endpoint's parameters by key, join as k=v&k=v, HMAC-SHA256
with the secret, send the hex digest in MSG-SIGNATURE and the key in RST-API-KEY. GET sends the
signed string as the query; POST sends it verbatim as a form-urlencoded body. Only the
parameters the endpoint lists are signed, so nothing else is ever added to a request.

Failed requests still come back HTTP 200 with {"Success": false, "ErrMsg": ...}; every call
checks Success. Zero-valued numeric fields are omitted by the server, so callers use .get(x, 0).
"""
import hashlib
import hmac
import json
import logging
import time

import requests

from bot.config import settings as S

log = logging.getLogger(__name__)

_NO_RESULT = ("no order matched", "no pending order")   # Success=false that means "empty"


class RoostooError(Exception):
    """The API answered, but with Success=false (a business error, not retried)."""


class RoostooUnavailable(Exception):
    """Network or server failure after all retries."""


def sign(params: dict, secret: str):
    """Returns (query_string, signature) for the given parameters."""
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sig = hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    return qs, sig


def _requests_transport(method, url, headers, data, timeout):
    r = requests.request(method, url, headers=headers, data=data, timeout=timeout)
    return r.status_code, r.text


class RoostooClient:
    def __init__(self, api_key: str, secret: str, limiter, base_url: str = S.ROOSTOO_URL,
                 timeout: float = S.HTTP_TIMEOUT_SEC, max_retries: int = S.MAX_RETRIES,
                 transport=_requests_transport, sleeper=time.sleep):
        self.api_key, self.secret = api_key, secret
        self.limiter = limiter
        self.base = base_url.rstrip("/")
        self.timeout, self.max_retries = timeout, max_retries
        self.transport, self.sleeper = transport, sleeper

    # --- plumbing ------------------------------------------------------------------------
    @staticmethod
    def _ts() -> str:
        return str(int(time.time() * 1000))

    def _request(self, method: str, path: str, params: dict = None, signed: bool = False) -> dict:
        params = {k: str(v) for k, v in (params or {}).items() if v is not None}
        qs, sig = sign(params, self.secret) if signed else (
            "&".join(f"{k}={params[k]}" for k in sorted(params)), None)
        headers = {}
        if signed:
            headers["RST-API-KEY"] = self.api_key
            headers["MSG-SIGNATURE"] = sig
        url = self.base + path
        data = None
        if method == "GET":
            if qs:
                url += "?" + qs
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = qs
        last = None
        for attempt in range(self.max_retries):
            self.limiter.acquire()
            try:
                status, text = self.transport(method, url, headers, data, self.timeout)
                if status != 200:
                    last = f"HTTP {status}: {text[:200]}"
                else:
                    body = json.loads(text)
                    if body.get("Success") is False:
                        raise RoostooError(body.get("ErrMsg") or "unknown error")
                    return body
            except RoostooError:
                raise
            except (requests.RequestException, ValueError, OSError) as e:
                last = f"{type(e).__name__}: {e}"
            log.warning("roostoo %s %s attempt %d failed: %s", method, path, attempt + 1, last)
            self.sleeper(min(2 ** attempt, 8))
        raise RoostooUnavailable(f"{method} {path}: {last}")

    # --- public endpoints ------------------------------------------------------------------
    def server_time(self) -> int:
        return int(self._request("GET", "/v3/serverTime")["ServerTime"])

    def exchange_info(self) -> dict:
        return self._request("GET", "/v3/exchangeInfo")

    def ticker(self, pair: str = None) -> dict:
        """{pair: {MaxBid, MinAsk, LastPrice, ...}} for one pair or all."""
        p = {"timestamp": self._ts()}
        if pair:
            p["pair"] = pair
        return self._request("GET", "/v3/ticker", p)["Data"]

    # --- signed endpoints -----------------------------------------------------------------
    def balance(self) -> dict:
        """{coin: {"Free": x, "Lock": y}}"""
        body = self._request("GET", "/v3/balance", {"timestamp": self._ts()}, signed=True)
        return body.get("Wallet") or body.get("SpotWallet") or {}

    def place_order(self, pair: str, side: str, quantity: str, order_type: str = "MARKET",
                    price: str = None) -> dict:
        p = {"pair": pair, "side": side, "type": order_type, "quantity": quantity, "timestamp": self._ts()}
        if price is not None:
            p["price"] = price
        return self._request("POST", "/v3/place_order", p, signed=True)

    def query_order(self, order_id=None, pair=None, pending_only=None) -> list:
        p = {"timestamp": self._ts()}
        if order_id is not None:
            p["order_id"] = order_id
        else:
            if pair:
                p["pair"] = pair
            if pending_only is not None:
                p["pending_only"] = "TRUE" if pending_only else "FALSE"
        try:
            return self._request("POST", "/v3/query_order", p, signed=True).get("OrderMatched", [])
        except RoostooError as e:
            if any(s in str(e).lower() for s in _NO_RESULT):
                return []
            raise

    def cancel_order(self, order_id=None, pair=None) -> list:
        p = {"timestamp": self._ts()}
        if order_id is not None:
            p["order_id"] = order_id
        elif pair:
            p["pair"] = pair
        return self._request("POST", "/v3/cancel_order", p, signed=True).get("CanceledList", [])

    def short_open(self, pair: str, collateral: str) -> dict:
        p = {"pair": pair, "collateral": collateral, "timestamp": self._ts()}
        return self._request("POST", "/v6/short_open", p, signed=True)

    def short_close(self, pair: str, close_qty: str = None, close_pct: str = None) -> dict:
        p = {"pair": pair, "timestamp": self._ts()}
        if close_qty is not None:
            p["close_qty"] = close_qty
        elif close_pct is not None:
            p["close_pct"] = close_pct
        return self._request("POST", "/v6/short_close", p, signed=True)

    def short_positions(self) -> list:
        body = self._request("GET", "/v6/short_positions", {"timestamp": self._ts()}, signed=True)
        return body.get("Positions") or []
