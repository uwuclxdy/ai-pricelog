from __future__ import annotations

import httpx
import pytest
from bs4 import BeautifulSoup

from ai_pricelog import web


def test_fetch_text_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        web.fetch_text("ftp://example.com/file")


def _response(status: int, url: str, text: str = "") -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", url), text=text)


class _SeqClient:
    def __init__(self, responses: list[tuple[int, str]], **kwargs):
        self.responses = list(responses)
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self, url: str):
        self.calls += 1
        status, text = self.responses.pop(0)
        return _response(status, url, text)


def test_fetch_text_retries_transient_5xx(monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda _: None)
    client = _SeqClient([(504, ""), (504, ""), (200, "ok body")])
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: client)
    assert web.fetch_text("https://example.com/x") == "ok body"


def test_fetch_text_fails_after_the_retry_budget(monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda _: None)
    client = _SeqClient([(504, "")] * 4)
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(web.FetchError, match="https://example.com/x"):
        web.fetch_text("https://example.com/x")
    assert client.calls == 4


def test_fetch_text_does_not_retry_4xx(monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda _: None)
    client = _SeqClient([(404, "nope")])
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(web.FetchError, match="404"):
        web.fetch_text("https://example.com/x")
    assert client.calls == 1


def test_fetch_error_wraps_transport_errors(monkeypatch):
    class BoomClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def get(self, url):
            raise httpx.ConnectError("no route", request=httpx.Request("GET", url))

    monkeypatch.setattr(web.httpx, "Client", BoomClient)
    with pytest.raises(web.FetchError, match="https://example.com/x"):
        web.fetch_text("https://example.com/x")


def test_extract_tables_skips_nested_tables():
    soup = BeautifulSoup(
        """
        <table>
          <tr><td>1</td><td>2</td></tr>
          <tr><td><table><tr><td>nested</td></tr></table></td><td>3</td></tr>
        </table>
        <table><tr><th>h1</th><th>h2</th></tr></table>
        """,
        "html.parser",
    )
    assert web.extract_tables(soup) == [
        [["1", "2"], ["nested", "3"]],
        [["h1", "h2"]],
    ]


def test_extract_tables_joins_cell_text():
    soup = BeautifulSoup("<table><tr><td>a<b>b</b> c</td></tr></table>", "html.parser")
    assert web.extract_tables(soup) == [[["a b c"]]]
