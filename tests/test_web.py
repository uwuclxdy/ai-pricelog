import httpx
import pytest
from bs4 import BeautifulSoup

from litellm_autopr import web


def test_fetch_text_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        web.fetch_text("ftp://example.com/file")


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
