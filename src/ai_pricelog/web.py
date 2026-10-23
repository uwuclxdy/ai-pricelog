"""http fetch helpers: fetch_text, fetch_soup, and table extraction."""

from __future__ import annotations

import html
import re
import sys
import time
import unicodedata
import urllib.parse
from collections.abc import Iterator

import httpx
from bs4 import BeautifulSoup, Tag


class FetchError(Exception):
    """a fetch failed after retries; the message names the url."""


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"url scheme must be http or https: {url!r}")
    # offer post_handshake_auth (TLS extension 49) as urllib and curl do: www.ai21.com's
    # Cloudflare challenge answered a GitHub runner 403 without it and 200 with it,
    # 4/4 rounds each (2026-10-15)
    ssl_context = httpx.create_ssl_context()
    if ssl_context.post_handshake_auth is not None:
        ssl_context.post_handshake_auth = True
    try:
        with httpx.Client(
            transport=httpx.HTTPTransport(retries=3, verify=ssl_context),
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        ) as client:
            # the transport retries connect errors only; a transient
            # 5xx/429 completes the round trip and would fail unretried
            for attempt in range(4):
                response = client.get(url)
                if response.status_code < 500 and response.status_code != 429:
                    break
                time.sleep(0.5 * attempt)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed for {url}: {exc}") from exc


def fetch_soup(url: str, headers: dict[str, str] | None = None) -> BeautifulSoup:
    return BeautifulSoup(fetch_text(url, headers), "html.parser")


# the one amount grammar every dollar-amount reader routes through
# amount_scan, two readers excepted (digitalocean's bare "$X" cell keeps a
# private fullmatch; novita reads its span-title attribute numbers with a
# bare float):
# ASCII digits, commas only in thousands groups that never open with a
# zero, an optional decimal part, and nothing numeric glued after it (a
# digit, or a comma/dot that continues the number). a comma-decimal
# ("$0,14", "$0,342") reads no amount; a real thousands group
# ("$1,000.14") and a punctuation comma after an amount ("$2.00, prompts")
# both read. a comma followed by optional whitespace and a digit continues
# the number only where it could be a decimal comma (see
# `_spaced_comma_continues`): "$0, 30" reads no amount, while "$0.30, 1M
# context" reads 0.30.
# a non-ASCII separator between digits ("$0．30", "$1，000") also continues
# the number, so its leading digits never read alone, and a digit-hyphen-
# digit run ("$1-2") is a range, never a number, like the en-dash form.
_AMOUNT_NUMBER = (
    r"(?:[1-9]\d{0,2}(?:,\d{3})+|\d+)(?:\.\d+)?(?!(?u:[\d,.]*\d))"
    r"(?!(?u:[^\x00-\x7f\s]\d))(?!-\d)"
)

_AMOUNT_FULL_RE = re.compile(_AMOUNT_NUMBER, re.ASCII)
# `\d` stays Unicode in these two and in the `(?u:)` guards inside
# `_AMOUNT_NUMBER`: a fullwidth digit is amount-shaped and reads malformed
_RUN_START_RE = re.compile(r"(?<![\d,.])(?<!\d[^\x00-\x7f\s])(?<!\d-)[.,]?\d")
_MALFORMED_AFTER_RE = re.compile(r"\s*[.,]?\d")
# a run that continues a number through a comma + optional spaces is a
# spaced comma-decimal ("0, 60 USD"), never a fresh adjacent number, but
# only where the comma could be a decimal comma ("0.30, 0.60 USD" is a list)
_SPACED_COMMA_BEFORE_RE = re.compile(r"([\d,.]*\d),\s*$")
_SPACED_COMMA_AFTER_RE = re.compile(r",\s*(\d[\d,.]*)")
# every Unicode dash (category Pd) plus the non-Pd dash-likes a page can
# spell a range with (~, ～, −): a dash-like between two numbers opens a range
_DASH_LIKE = (
    "".join(chr(cp) for cp in range(0x110000) if unicodedata.category(chr(cp)) == "Pd") + "~～−"
)
_DASH_CLASS = "[" + re.escape(_DASH_LIKE) + "]"

# the after-marker half of the range check: a run start that follows
# "digit dash-like" ("0.30 - 0.60 USD") is a range bound. the before-marker
# half carries the reader's own marker, so amount_scan builds it per call
_RANGE_BEFORE_RE = re.compile(r"\d\s*(?:" + _DASH_CLASS + r"|(?<=\s)to(?=\s))\s*$")

# a "$"-marker reader also refuses the other dollar spellings a cell can
# carry beside its real "$" amount. html.unescape folds every entity
# spelling of "$", "＄" or "﹩" into its character first, then the scan
# flags a "＄" or "﹩" before digits, or a "$"/"＄"/"﹩" after digits with
# no amount after it ("10$", "10 $", "10 ＄")
_OTHER_DOLLAR_RE = re.compile(r"[＄﹩]\s*[.,]?\d|\d\s*[$＄﹩](?!\s*[.,]?\d)")

# the entity shape html.unescape decodes; a "$" one sitting before a digit
# is a second amount the raw-text reader never saw ("&#36;10", "&#36 10")
_ENTITY_RE = re.compile(r"&(?:#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)")

# Python's int-string conversion limit (sys.get_int_max_str_digits(), 4300)
# makes html.unescape raise ValueError on a decimal character reference whose
# digit run is longer (measured: `&#` + 5000 nines + `;`, the zero-padded
# `&#000…065;` and the unterminated form all raise; a hex ref does not).
# unescape rewrites such a ref to its short same-value form first: a value
# past U+10FFFF collapses to `&#1114112;` (html.unescape reads that as U+FFFD,
# the read a short out-of-range ref already gives), a zero-padded one keeps
# its significant digits (leading zeros carry no value).
_HUGE_DECIMAL_REF_RE = re.compile(rf"&#([0-9]{{{sys.get_int_max_str_digits() + 1},}})(;?)")


def _huge_decimal_ref(match: re.Match[str]) -> str:
    """the short same-value form of a decimal ref too long for int()."""
    significant = match.group(1).lstrip("0") or "0"
    if len(significant) > 7:
        significant = "1114112"  # U+10FFFF + 1: out of range, reads as U+FFFD
    return "&#" + significant + match.group(2)


def unescape(text: str) -> str:
    """`text` with HTML entities decoded exactly like html.unescape, without
    int()'s digit-run limit raising on a long decimal character reference."""
    return html.unescape(_HUGE_DECIMAL_REF_RE.sub(_huge_decimal_ref, text))


_DECIMAL_DOT_RE = re.compile(r"\d\.\d")


def _spaced_comma_continues(before_run: str, after_run: str) -> bool:
    """a comma + optional spaces + digit continues the number only where it
    could be a decimal comma: no decimal dot (a "." between two digits, never
    a sentence period) on either side, and no thousands comma before it."""
    return (
        _DECIMAL_DOT_RE.search(before_run) is None
        and _DECIMAL_DOT_RE.search(after_run) is None
        and "," not in before_run
    )


def _decoded_dollar_before_digit(text: str) -> bool:
    """an entity that html.unescape folds into "$" and that sits before a
    digit: the second amount the raw-text reader never saw."""
    for match in _ENTITY_RE.finditer(text):
        if unescape(match.group(0)) == "$" and _MALFORMED_AFTER_RE.match(text, match.end()):
            return True
    return False


def _other_dollar_malformed(text: str) -> bool:
    """a dollar spelling beside a digit that is not the reader's own marker."""
    unescaped = unescape(text)
    return _OTHER_DOLLAR_RE.search(unescaped) is not None or _decoded_dollar_before_digit(text)


def amount_scan(text: str, *, before: str = "", after: str = "") -> tuple[list[str], bool]:
    """the readable amount numbers in `text`, and whether an amount-shaped
    token the grammar cannot read is present.

    `before`/`after` are the currency-marker strings sitting immediately on
    either side of each number ("$0.14" -> before="$"; "0.60 USD" ->
    after=" USD"; "USD 0.0636" -> before="USD "; a bare numeric cell -> both
    ""). a malformed amount reads no number and sets the second result True;
    a cell with no amount-shaped token returns ([], False); a suffix marker
    with no adjacent number contributes nothing. at most one of
    `before`/`after` may be set.
    """
    if before and after:
        raise ValueError("amount_scan takes at most one of `before` and `after`")
    if before:
        full = re.compile(re.escape(before) + "(" + _AMOUNT_NUMBER + ")", re.ASCII)
        # a readable amount, then a dash-like, then optionally the reader's
        # own marker and a number opens a range ("$0.3 - 0.6", "$0.3-$0.6");
        # a number that is a percent or a K/M/B/x unit is prose, not a bound
        range_after = re.compile(
            r"\s*(?:"
            + _DASH_CLASS
            + r"|(?<=\s)to(?=\s))\s*(?:"
            + re.escape(before)
            + r")?\s*[.,]?\d(?![\d,.]*\s*(?:%|[KkMmBb]\b|x\b))"
        )
        readable: list[str] = []
        malformed = False
        for match in re.finditer(re.escape(before), text):
            token = full.match(text, match.start())
            if token is None:
                if _MALFORMED_AFTER_RE.match(text, match.end()):
                    malformed = True
                continue
            # after a marker, a comma + optional spaces + a digit continues
            # the number only where it could be a decimal comma: "$0, 30" is
            # a spaced comma-decimal, never 0, while "$0.30, 1M" reads 0.30
            if range_after.match(text, token.end()):
                malformed = True
            after_run = _SPACED_COMMA_AFTER_RE.match(text, token.end())
            if after_run is not None and _spaced_comma_continues(
                token.group(1), after_run.group(1)
            ):
                malformed = True
            else:
                readable.append(token.group(1))
        if before == "$" and _other_dollar_malformed(text):
            malformed = True
        return readable, malformed
    if after:
        readable: list[str] = []
        malformed = False
        for marker in re.finditer(re.escape(after), text):
            start = None
            for run in _RUN_START_RE.finditer(text, 0, marker.start()):
                start = run.start()
            if start is None:
                continue
            token = _AMOUNT_FULL_RE.match(text, start)
            if token is None:
                malformed = True
                continue
            if token.end() != marker.start():
                # a number that ends short of the marker has no adjacent
                # amount; the marker contributes nothing
                continue
            if _RANGE_BEFORE_RE.search(text[:start]):
                malformed = True
            before_run = _SPACED_COMMA_BEFORE_RE.search(text[:start])
            if before_run is not None and _spaced_comma_continues(
                before_run.group(1), token.group(0)
            ):
                malformed = True
                continue
            readable.append(token.group(0))
        return readable, malformed
    readable = []
    malformed = False
    for run in _RUN_START_RE.finditer(text):
        token = _AMOUNT_FULL_RE.match(text, run.start())
        if token is not None:
            readable.append(token.group(0))
        else:
            malformed = True
    return readable, malformed


def unreadable_rate_error(cell: str, model_id: str, url: str) -> FetchError:
    """a FetchError naming a cell whose amount the grammar cannot read."""
    return FetchError(f"unreadable rate {cell!r} for {model_id} on {url}")


def fold_heading(text: str) -> str:
    """fold case, whitespace, and &/and for pinned-header comparison."""
    return " ".join(text.casefold().replace("&", " and ").split())


_MARKDOWN_LINE_END = re.compile(r"\r\n?|\n")


def markdown_lines(text: str) -> list[str]:
    """split a markdown page on CommonMark line endings only.

    str.splitlines() also cuts on U+2028, U+0085 and other separators a cell
    can carry, tearing one table row into two.
    """
    return _MARKDOWN_LINE_END.split(text)


def markdown_pipe_blocks(text: str) -> list[list[str]]:
    """consecutive pipe lines, one list per markdown table block."""
    blocks: list[list[str]] = []
    block: list[str] = []
    for line in markdown_lines(text):
        if "|" in line:
            block.append(line)
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    return blocks


def extract_markdown_tables(text: str) -> list[list[list[str]]]:
    """split markdown pipe tables into row lists: header, separator, data rows."""
    tables: list[list[list[str]]] = []
    for lines in markdown_pipe_blocks(text):
        # one edge pipe per side: `|| x |` opens with an empty cell
        rows = [
            [cell.strip() for cell in line.strip().removeprefix("|").removesuffix("|").split("|")]
            for line in lines
        ]
        if len(rows) >= 2 and all(re.fullmatch(r":?-+:?", cell) for cell in rows[1]):
            tables.append(rows)
    return tables


def extract_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        tables.append(
            [
                [
                    cell.get_text(" ", strip=True)
                    for cell in row.find_all(["th", "td"])
                    if cell.find_parent("table") is table
                ]
                for row in table.find_all("tr")
                if row.find_parent("table") is table
            ]
        )
    return tables


def own_rows(table: Tag) -> Iterator[Tag]:
    """the table's own body rows in document order.

    an own body row is a <tr> whose nearest table is this table and whose
    nearest row group (thead, tbody, tfoot, or the table itself) is not a
    thead: rows in any tbody, directly under the table, or in a tfoot all
    count; a row an omitted </tr> nests inside another, or one under a
    wrapper between the group and the row, still counts; a nested table's
    rows never do.
    """
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        group = row.find_parent(["thead", "tbody", "tfoot", "table"])
        if group is not None and group.name != "thead":
            yield row


def own_cells(row: Tag) -> list[Tag]:
    """the row's own cells: the th/td cells whose nearest tr is this row.

    a cell under a wrapper element still counts; a nested table's cells
    never do (their nearest tr is the nested row).
    """
    return [cell for cell in row.find_all(["th", "td"]) if cell.find_parent("tr") is row]


def header_labels(table: Tag) -> tuple[str, ...]:
    """the table's own header labels, folded with fold_heading.

    the own thead only, so a layout table never borrows a nested table's
    header. a thead row after the first that carries no own <th> cell is a
    body row swallowed into the header: own_rows drops such a row silently,
    so the label read raises instead of hiding the model. the labels come
    from the first own row's own <th> cells, or from the thead's own <th>
    cells when the thead holds no <tr>.
    """
    thead = table.find("thead", recursive=False)
    if thead is None:
        return ()
    rows = thead.find_all("tr", recursive=False)
    for row in rows[1:]:
        if not any(cell.name == "th" for cell in own_cells(row)):
            raise FetchError(f"table header holds {len(rows)} rows")
    if rows:
        cells = [cell for cell in own_cells(rows[0]) if cell.name == "th"]
    else:
        cells = thead.find_all("th", recursive=False)
    return tuple(fold_heading(cell.get_text(" ", strip=True)) for cell in cells)
