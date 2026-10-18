from __future__ import annotations

import ssl
from pathlib import Path

import certifi
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


@pytest.mark.parametrize("ca_source", ["certifi", "SSL_CERT_FILE", "SSL_CERT_DIR"])
def test_fetch_text_offers_post_handshake_auth_with_full_verification(
    monkeypatch, tmp_path, ca_source
):
    # one known CA through certifi and SSL_CERT_FILE, and SSL_CERT_DIR handed to
    # the context, so the transport's context is checked for each of httpx's
    # trust sources, not only its flags
    bundle = Path(certifi.where()).read_text()
    begin = bundle.index("-----BEGIN CERTIFICATE-----")
    end = bundle.index("-----END CERTIFICATE-----", begin) + len("-----END CERTIFICATE-----")
    one_ca = tmp_path / "one-ca.pem"
    one_ca.write_text(bundle[begin:end] + "\n")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    capath_loads = []
    real_load = ssl.SSLContext.load_verify_locations

    def recording_load(self, cafile=None, capath=None, cadata=None):
        capath_loads.append((self, capath))
        return real_load(self, cafile, capath, cadata)

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", recording_load)
    if ca_source == "certifi":
        monkeypatch.setattr(certifi, "where", lambda: str(one_ca))
    elif ca_source == "SSL_CERT_FILE":
        monkeypatch.setenv("SSL_CERT_FILE", str(one_ca))
    else:
        monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    contexts = []
    real_transport = web.httpx.HTTPTransport

    def recording_transport(*args, **kwargs):
        contexts.append(kwargs.get("verify", args[0] if args else None))
        return real_transport(*args, **kwargs)

    monkeypatch.setattr(web.httpx, "HTTPTransport", recording_transport)
    client = _SeqClient([(200, "ok body")])
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: client)
    assert web.fetch_text("https://example.com/x") == "ok body"
    assert len(contexts) == 1
    context = contexts[0]
    assert isinstance(context, ssl.SSLContext)
    assert context.post_handshake_auth is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    if ca_source == "SSL_CERT_DIR":
        # a capath stays out of get_ca_certs until a handshake looks a CA up
        # (measured 2026-10-15, CPython 3.12.15 / OpenSSL 3.5.9), so the
        # directory is bound through the load call itself
        assert context.get_ca_certs(binary_form=True) == []
        assert [capath for ctx, capath in capath_loads if ctx is context] == [str(tmp_path)]
    else:
        one_ca_der = ssl.PEM_cert_to_DER_cert(bundle[begin:end])
        assert context.get_ca_certs(binary_form=True) == [one_ca_der]


def test_fetch_text_skips_post_handshake_auth_where_the_build_lacks_it(monkeypatch):
    # a TLS build without post-handshake auth reads the attribute as None, the
    # case the stdlib's own https context guards: the fetch still goes out
    class NoPostHandshakeAuth(ssl.SSLContext):
        @property
        def post_handshake_auth(self):
            return None

    monkeypatch.setattr(
        web.httpx,
        "create_ssl_context",
        lambda *args, **kwargs: NoPostHandshakeAuth(ssl.PROTOCOL_TLS_CLIENT),
    )
    client = _SeqClient([(200, "ok body")])
    monkeypatch.setattr(web.httpx, "Client", lambda **kwargs: client)
    assert web.fetch_text("https://example.com/x") == "ok body"


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


def test_markdown_table_keeps_a_line_separator_inside_a_cell():
    # str.splitlines() also cuts on U+2028, tearing one row into two
    text = "| a | b |\n|---|---|\n| x\u2028y | z |\n"
    assert web.extract_markdown_tables(text) == [[["a", "b"], ["---", "---"], ["x\u2028y", "z"]]]


def test_markdown_table_drops_a_line_separator_at_a_row_edge():
    text = "| a | b |\u2028\n|---|---|\n| x | y |\u2028\n"
    assert web.extract_markdown_tables(text) == [[["a", "b"], ["---", "---"], ["x", "y"]]]


@pytest.mark.parametrize("newline", ["\r\n", "\r"], ids=["crlf", "bare-cr"])
def test_markdown_table_reads_commonmark_line_endings(newline):
    text = newline.join(["| a | b |", "|---|---|", "| x | y |", ""])
    assert web.extract_markdown_tables(text) == [[["a", "b"], ["---", "---"], ["x", "y"]]]


def test_markdown_table_keeps_empty_edge_cells():
    # `||` opens or closes a row with an empty cell; stripping every edge pipe drops it
    text = "| | a | b |\n|---|---|---|\n|| x | y |\n| x | y ||\n"
    assert web.extract_markdown_tables(text) == [
        [["", "a", "b"], ["---", "---", "---"], ["", "x", "y"], ["x", "y", ""]]
    ]


def test_markdown_table_reads_rows_without_outer_pipes():
    text = "a | b\n--- | ---\nx | y\n"
    assert web.extract_markdown_tables(text) == [[["a", "b"], ["---", "---"], ["x", "y"]]]


def test_amount_scan_reads_a_thousands_group():
    assert web.amount_scan("$1,000.14", before="$") == (["1,000.14"], False)


def test_amount_scan_rejects_a_comma_decimal():
    assert web.amount_scan("$0,14", before="$") == ([], True)


def test_amount_scan_rejects_a_trailing_glued_digit():
    assert web.amount_scan("$1,5000", before="$") == ([], True)


def test_amount_scan_reads_two_amounts():
    assert web.amount_scan("$0.30 $0.06 (cached)", before="$") == (["0.30", "0.06"], False)


def test_amount_scan_dollar_prefix():
    assert web.amount_scan("$0.14", before="$") == (["0.14"], False)
    assert web.amount_scan("$0,14", before="$") == ([], True)


def test_amount_scan_dollar_suffix():
    assert web.amount_scan("0.60 USD", after=" USD") == (["0.60"], False)
    assert web.amount_scan("0,60 USD", after=" USD") == ([], True)


def test_amount_scan_usd_prefix():
    assert web.amount_scan("USD 0.0636", before="USD ") == (["0.0636"], False)
    assert web.amount_scan("USD 0,0636", before="USD ") == ([], True)


def test_amount_scan_bare_number():
    assert web.amount_scan("0.25") == (["0.25"], False)
    assert web.amount_scan("0,25") == ([], True)


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        # punctuation around a readable amount is prose, not a malformed amount,
        # whichever side the currency marker sits on
        ("2.00, 4.00", {}, (["2.00", "4.00"], False)),
        ("0.25.", {}, (["0.25"], False)),
        ("December 31, 2026.", {}, (["31", "2026"], False)),
        ("$2.00, prompts", {"before": "$"}, (["2.00"], False)),
        ("0.60 USD, cached", {"after": " USD"}, (["0.60"], False)),
        # after a currency marker, a comma before a digit continues the number:
        # a spaced comma-decimal is unreadable, never its whole-number part
        ("$0, 30", {"before": "$"}, ([], True)),
        ("$5, 5", {"before": "$"}, ([], True)),
        # a leading dot is part of the number, never stripped into a bigger one
        (".60 USD", {"after": " USD"}, ([], True)),
        # digits are ASCII only, on every path
        ("\uff10.25", {}, ([], True)),
        ("$\uff10.25", {"before": "$"}, ([], True)),
    ],
)
def test_amount_scan_token_edges(text, kwargs, expected):
    assert web.amount_scan(text, **kwargs) == expected


def test_amount_scan_takes_one_marker_side():
    with pytest.raises(ValueError, match="at most one"):
        web.amount_scan("$1 USD", before="$", after=" USD")


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        # a continuation written with a non-ASCII space or digit still continues
        # the number, so the leading digits never read alone
        ("$0,\u00a030", {"before": "$"}, ([], True)),
        ("$0,\u200930", {"before": "$"}, ([], True)),
        ("$0.\uff13\uff10", {"before": "$"}, ([], True)),
        ("$1\uff15", {"before": "$"}, ([], True)),
        ("USD 0.\uff13", {"before": "USD "}, ([], True)),
        # a suffix marker not right after the number reads nothing for that
        # marker, never "malformed"
        ("0.60 USD (billed in USD)", {"after": " USD"}, (["0.60"], False)),
        # the spaced comma-decimal rule holds on the suffix side too
        ("0, 60 USD", {"after": " USD"}, ([], True)),
    ],
)
def test_amount_scan_unicode_and_suffix_edges(text, kwargs, expected):
    assert web.amount_scan(text, **kwargs) == expected


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        # a spaced comma continues a number only where it could be a decimal
        # comma: neither side of it carries a "."
        ("$0.30, 1M context", {"before": "$"}, (["0.30"], False)),
        ("USD 0.06, 1M tokens", {"before": "USD "}, (["0.06"], False)),
        ("0.30, 0.60 USD", {"after": " USD"}, (["0.60"], False)),
        ("Tier 1, 0.60 USD", {"after": " USD"}, (["0.60"], False)),
        # a suffix marker with no number right before it contributes nothing,
        # whatever sits earlier in the cell
        ("0.60 USD (tiers 1, 2 in USD)", {"after": " USD"}, (["0.60"], False)),
        ("1, 5 tokens for USD", {"after": " USD"}, ([], False)),
    ],
)
def test_amount_scan_spaced_comma_reach(text, kwargs, expected):
    assert web.amount_scan(text, **kwargs) == expected


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        # a sentence period is no decimal dot: only a "." between two digits
        # makes the comma a list separator
        ("$0, 30.", {"before": "$"}, ([], True)),
        ("Price $0, 30. Then", {"before": "$"}, ([], True)),
        ("$5, 5.", {"before": "$"}, ([], True)),
        ("USD 0, 5.", {"before": "USD "}, ([], True)),
        # a run already holding a thousands comma is no decimal-comma whole part
        ("$1,000, 5", {"before": "$"}, (["1,000"], False)),
        ("1,000, 60 USD", {"after": " USD"}, (["60"], False)),
    ],
)
def test_amount_scan_spaced_comma_dot_and_thousands(text, kwargs, expected):
    assert web.amount_scan(text, **kwargs) == expected


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        # a leading-dot run is no decimal number: ".5, 60" stays a comma-decimal
        (".5, 60 USD", {"after": " USD"}, ([], True)),
        ("Ver.0, 60 USD", {"after": " USD"}, ([], True)),
        # a non-ASCII separator between digits continues the number, so its
        # leading digits never read alone
        ("$0\uff0e30", {"before": "$"}, ([], True)),
        ("$1\uff0c000", {"before": "$"}, ([], True)),
        ("$0\u066b30", {"before": "$"}, ([], True)),
        ("$0\u00b730", {"before": "$"}, ([], True)),
        ("0\uff0e30 USD", {"after": " USD"}, ([], True)),
        ("0\uff0e30", {}, ([], True)),
        # a separate non-ASCII token after a readable amount still reads
        ("$0.30 \uff15", {"before": "$"}, (["0.30"], False)),
    ],
)
def test_amount_scan_non_ascii_separators(text, kwargs, expected):
    assert web.amount_scan(text, **kwargs) == expected


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        # a non-ASCII space still separates two numbers
        ("$0.30\u00a05", {"before": "$"}, (["0.30"], False)),
        ("$0.30\u20095", {"before": "$"}, (["0.30"], False)),
        # a non-ASCII character after something other than a digit starts a number
        ("x\u20130.60 USD", {"after": " USD"}, (["0.60"], False)),
        ("\u20ac0.30 2", {}, (["0.30", "2"], False)),
    ],
)
def test_amount_scan_non_ascii_separator_reach(text, kwargs, expected):
    assert web.amount_scan(text, **kwargs) == expected
