"""detect claude model ids from the anthropic pricing markdown twin.

reads https://platform.claude.com/docs/en/about-claude/pricing.md (the
machine-readable surface llms.txt advertises). the "Model pricing" table
carries Model | Base Input Tokens | 5m Cache Writes | 1h Cache Writes |
Cache Hits & Refreshes | Output Tokens; the header pins after folding
case, whitespace, and &/and, so wording drift ("base input tokens",
"cache hits and refreshes") still matches, while the other tables further
down the page (fast mode, batch) never match. rows outside the six-cell
shape and names the name-shape guard rejects skip with a warning (a
rejected rename of a tracked model drops that model rather than minting
a fake id), and a page whose model table or model rows are gone still
raises.

one `split_name` parse reads every model-table name; fast-table names
match model-table ids through their slug, never the shape check. sup
footnote markup, every `([text](url))` link annotation (balanced parens
inside the text and the url) and a trailing paren group carrying a link
drop, and HTML entities (`&nbsp;` is a space) unescape. markdown emphasis
and code marks (`*`, `_`, `` ` ``), every Unicode format (Cf) character
and U+034F: a maximal run of them between two ASCII letters joins the
letters (the run drops), and a run touching a non-letter on either side
reads as one space, except U+200B, U+200C, U+200D, U+2060 and U+FEFF, which
always read as a space and split a run. a trailing link-less paren
mentioning prompts or tokens then splits off as a prompt-length tier
qualifier, dropped off the id and read (FetchError when its wording or
threshold is unreadable); such a paren holding a comparison (up to, over,
above, under, below, beyond, more/less than, exceed..., <, >, ≤, ≥, read
after entities and marks; an HTML tag's < and > are markup, not a
comparison) is a drifted tier wording and raises the wording error, and
any other prompt/token paren names a model variant and raises the
qualifier error, still blamed on the stem's model. the tier-wording
message quotes the paren as the page writes it, whatever follows it
(whitespace, marks, entities, or a link annotation) and however its
close is spelled (an entity close included).
the remaining name must have a model name's
shape — "Claude", one or more words of ASCII letters, a version, then
optionally "(Fast)" — and a name without it raises FetchError carrying
the id its leading shape names (no id when no leading shape is present,
or when the version is followed by another digit group after any run of
characters that are not a word character, `(` or `[`), so detection skips
that row with a warning. names
slug lowercase with non-alphanumeric runs collapsed to dashes ("Claude
Opus 4.1" -> claude-opus-4-1).
"""

from __future__ import annotations

import logging
import re
import unicodedata

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_markdown_tables, fetch_text, fold_heading, unescape

log = logging.getLogger(__name__)

TABLE_HEADER = [
    "Model",
    "Base Input Tokens",
    "5m Cache Writes",
    "1h Cache Writes",
    "Cache Hits & Refreshes",
    "Output Tokens",
]

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SUP_RE = re.compile(r"<sup>.*?</sup>", re.DOTALL)
_TIER_RE = re.compile(
    r"\(for\s+prompts\s+(up\s+to|over)\s+(\S+)\s+(?:input\s+)?tokens\)",
    re.IGNORECASE,
)
_THRESHOLD_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)[kK]?$", re.ASCII)
# a page-written token past this length is no threshold or rate the page means
_SANE_TOKEN_LENGTH = 32
_PROMPT_OR_TOKEN_RE = re.compile(r"\b(?:prompts?|tokens?)\b", re.IGNORECASE)
# a tier wording holds a comparison (a threshold the price crosses); any
# other prompt/token paren names a model variant, not a price tier
_COMPARISON_RE = re.compile(
    r"\bup\s+to\b|\bover\b|\babove\b|\bunder\b|\bbelow\b|\bbeyond\b"
    r"|\bmore\s+than\b|\bless\s+than\b|\bexceed\w*|[<>≤≥]",
    re.IGNORECASE,
)
# an HTML tag's < and > are markup, not a comparison: drop tags before the
# comparison search, so "(1M token <em>context</em>)" reads as no comparison
_TAG_RE = re.compile(r"<[a-zA-Z/][^<>]*>")
# the name shape the guard accepts: "Claude", one or more words of ASCII
# letters, a version, then optionally "(Fast)". one pattern serves both
# checks: `fullmatch` pins the whole stem, `match` reads the same front as
# a prefix, so a name the guard rejects for its tail still names the model
# its leading shape does; the version ends at a version boundary, so a
# version followed by another digit group after any run of characters that
# are not a word character, `(` or `[` names no model. `(?a:...)` keeps
# the letters, the digits and the
# "(Fast)" literal ASCII while IGNORECASE folds only ASCII letters, so no
# case fold maps a non-ASCII letter onto an ASCII one; the whitespace
# stays unicode, so a run holding NBSP still counts as one space between
# words.
_SHAPE_RE = re.compile(
    r"Claude(?:\s+(?a:[a-zA-Z]+))+\s+(?a:\d+(?:\.\d+)*)"
    r"(?![^\w(\[]*\d)(?:\s*(?a:\(Fast\)))?",
    re.IGNORECASE,
)
# the five invisible characters that always read as a space (one may stand
# in for the space between words)
_FIVE_SPACE = frozenset("\u200b\u200c\u200d\u2060\ufeff")
# markdown emphasis and code marks plus U+034F join two ASCII letters they
# sit between and read as a space elsewhere; every other Cf character
# follows the same rule
_JOIN_MARKS = frozenset("*_`\u034f")
_ASCII_LETTER_RE = re.compile(r"[a-zA-Z]")


class _RowError(FetchError):
    """a FetchError carrying the id its row's name names in `model_id`."""

    model_id: str | None

    def __init__(self, message: str, model_id: str | None) -> None:
        super().__init__(message)
        self.model_id = model_id


def _match_table(name: str, open_ch: str, close_ch: str) -> dict[int, int]:
    """open-index -> the matching close-index for each `open_ch`/`close_ch`
    pair, matched LIFO (the annotation scan's own pairing)."""
    stack: list[int] = []
    matches: dict[int, int] = {}
    for i, ch in enumerate(name):
        if ch == open_ch:
            stack.append(i)
        elif ch == close_ch and stack:
            matches[stack.pop()] = i
    return matches


def _drop_link_annotations(name: str) -> str:
    """the name with every `([text](url))` link annotation dropped, wherever
    each sits (balanced parens allowed inside the text and the url); the
    bracket and paren match tables keep the scan linear."""
    brackets = _match_table(name, "[", "]")
    parens = _match_table(name, "(", ")")
    out: list[str] = []
    i = 0
    while i < len(name):
        if name[i : i + 2] != "([":
            out.append(name[i])
            i += 1
            continue
        close_bracket = brackets.get(i + 1)
        if (
            close_bracket is None
            or close_bracket + 1 >= len(name)
            or name[close_bracket + 1] != "("
        ):
            out.append(name[i])
            i += 1
            continue
        close_paren = parens.get(close_bracket + 1)
        if close_paren is None or close_paren + 1 >= len(name) or name[close_paren + 1] != ")":
            out.append(name[i])
            i += 1
            continue
        i = close_paren + 2
    return "".join(out)


def _is_mark(ch: str) -> bool:
    """whether `ch` reads as a space or joins two letters (a markdown mark,
    a Cf character or U+034F)."""
    return ch in _JOIN_MARKS or unicodedata.category(ch) == "Cf"


def _mark_space(name: str) -> str:
    """the name with a maximal run of markdown marks, Cf characters and
    U+034F dropped where it sits between two ASCII letters (the run joins
    them) and read as one space elsewhere; the five U+200B, U+200C, U+200D,
    U+2060 and U+FEFF always read as a space and split a run."""
    out: list[str] = []
    i = 0
    while i < len(name):
        ch = name[i]
        if ch in _FIVE_SPACE:
            out.append(" ")
            i += 1
            continue
        if _is_mark(ch):
            end = i + 1
            while end < len(name) and name[end] not in _FIVE_SPACE and _is_mark(name[end]):
                end += 1
            prev = name[i - 1] if i else ""
            nxt = name[end] if end < len(name) else ""
            if not _ASCII_LETTER_RE.fullmatch(prev) or not _ASCII_LETTER_RE.fullmatch(nxt):
                out.append(" ")
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _drop_sup(name: str) -> str:
    """the name with `<sup>…</sup>` footnote markup dropped."""
    return _SUP_RE.sub("", name)


def _drop_trailing_link_groups(base: str) -> str:
    """`base` with every trailing paren group carrying a link dropped,
    repeated while the new trailing group still carries one."""
    paren = _trailing_paren(base)
    while paren is not None and "](" in paren:
        base = base[: -len(paren)].strip()
        paren = _trailing_paren(base)
    return base


def _prepared(name: str) -> str:
    """the name with sup markup and every link annotation dropped, HTML
    entities unescaped, markdown marks and invisible format characters
    read as a space (or joined between two letters), every trailing paren
    group carrying a link dropped, and both ends trimmed."""
    base = _drop_sup(_drop_link_annotations(name))
    base = unescape(base)
    base = _mark_space(base).strip()
    return _drop_trailing_link_groups(base)


def _trailing_paren(name: str) -> str | None:
    """the trailing parenthesized group, or None when the name has no
    trailing `)` or its parens do not balance."""
    if not name.endswith(")"):
        return None
    depth = 0
    for i in range(len(name) - 1, -1, -1):
        if name[i] == ")":
            depth += 1
        elif name[i] == "(":
            depth -= 1
            if depth == 0:
                return name[i:]
    return None


def _mentions_prompts_or_tokens(paren: str) -> bool:
    return _PROMPT_OR_TOKEN_RE.search(paren) is not None


def _trailing_tier_paren(base: str) -> str | None:
    """the trailing link-less paren whose text mentions prompts or tokens."""
    paren = _trailing_paren(base)
    if paren is not None and _mentions_prompts_or_tokens(paren):
        return paren
    return None


def _trailing_entity_start(name: str, end: int) -> int | None:
    """the index of the `&` starting the entity whose `;` sits at `end - 1`,
    or None when the trailing `;` starts no entity."""
    i = end - 2
    while i >= 0 and ((name[i].isascii() and name[i].isalnum()) or name[i] == "#"):
        i -= 1
    return i if i >= 0 and name[i] == "&" else None


def _trailing_entity_paren(name: str, close_start: int) -> str | None:
    """the trailing paren group whose close is the entity at `close_start`,
    from the matching `(` through the entity's end, or None when its parens
    do not balance."""
    depth = 0
    for i in range(close_start - 1, -1, -1):
        if name[i] == ")":
            depth += 1
        elif name[i] == "(":
            if depth == 0:
                return name[i:]
            depth -= 1
    return None


def _page_tier_paren(name: str) -> str | None:
    """the trailing tier paren as the page writes it (sup markup and link
    annotations dropped, entities and marks intact inside the paren,
    trailing whitespace, marks and space-or-mark entities after the
    closing paren stripped, a close spelled as an entity kept), or None."""
    dropped = _drop_trailing_link_groups(_drop_sup(_drop_link_annotations(name)))
    end = len(dropped)
    while end > 0:
        ch = dropped[end - 1]
        if _is_mark(ch) or ch.isspace():
            end -= 1
            continue
        if ch == ";":
            start = _trailing_entity_start(dropped, end)
            if start is not None:
                decoded = unescape(dropped[start:end])
                if decoded and all(_is_mark(c) or c.isspace() for c in decoded):
                    end = start
                    continue
        break
    dropped = dropped[:end]
    if dropped.endswith(";"):
        start = _trailing_entity_start(dropped, len(dropped))
        if start is not None and unescape(dropped[start:]) == ")":
            return _trailing_entity_paren(dropped, start)
    return _trailing_tier_paren(dropped)


def _threshold(token: str, name: str) -> int:
    """the tier threshold token as an int: ASCII digits, bare or with
    thousands commas in proper three-digit groups, and an optional trailing
    K/k suffix for thousands; anything else, a token past a sane length
    included, is a page-shape break."""
    if len(token) > _SANE_TOKEN_LENGTH or _THRESHOLD_RE.match(token) is None:
        raise FetchError(
            f"unreadable prompt-length tier threshold {token!r} in {name!r}; "
            "fix: teach the anthropic tier parse this spelling"
        )
    k = token[-1] in "Kk"
    return int((token[:-1] if k else token).replace(",", "")) * (1000 if k else 1)


def _slug_base(base: str) -> str:
    return _NON_ALNUM_RE.sub("-", base.lower()).strip("-")


def _read_tier(paren: str, name: str) -> tuple[str, int]:
    """the tier paren's (kind, threshold); unreadable wording or an
    unreadable threshold is a page-shape break."""
    match = _TIER_RE.fullmatch(paren)
    if match is None:
        page_paren = _page_tier_paren(name) or paren
        if _COMPARISON_RE.search(_TAG_RE.sub("", paren)) is None:
            raise FetchError(
                f"unread model qualifier {page_paren!r} in {name!r}: the paren names a"
                " model variant, not a prompt-length tier; fix: teach the anthropic"
                " detector the model this qualifier names"
            )
        raise FetchError(
            f"unreadable prompt-length tier wording {page_paren!r} in {name!r}; "
            "fix: teach the anthropic tier parse this spelling"
        )
    kind = " ".join(match.group(1).split()).lower()
    return kind, _threshold(match.group(2), name)


def _stem_and_tier(name: str) -> tuple[str, str | None]:
    """the prepared stem (its trailing tier paren dropped) and that paren;
    never shape-checks and never raises."""
    base = _prepared(name)
    paren = _trailing_tier_paren(base)
    stem = (base[: -len(paren)] if paren is not None else base).strip()
    return stem, paren


def _shape_id(stem: str) -> str | None:
    """the id the leading shape of `stem` names, or None when there is none."""
    match = _SHAPE_RE.match(stem)
    if match is None:
        return None
    return _slug_base(match.group(0))


def _own_model_id(name: str) -> str | None:
    """the model id a display name's leading shape names, or None; the
    scraper reads it to blame a failing row on the model its name names."""
    return _shape_id(_prepared(name))


def _name_shape_error(name: str, url: str, own_id: str | None) -> _RowError:
    return _RowError(
        f"unreadable model name {name!r} on {url}; "
        "fix: teach the anthropic name parse this spelling",
        own_id,
    )


def _name_id(name: str) -> str:
    """the model id a display name's slug names, without reading its tier:
    sup, link annotations, trailing link-carrying groups and entities
    drop, marks and invisible characters read as a space or join two
    letters, then a trailing tier paren drops; everything else stays.
    never raises and never shape-checks."""
    stem, _paren = _stem_and_tier(name)
    return _slug_base(stem)


def _name_tier(name: str) -> tuple[str, int] | None:
    """the tier a display name's trailing tier paren reads, or None; never
    shape-checks. raises FetchError (carrying the slug in `model_id`) for
    unreadable tier wording or threshold."""
    stem, paren = _stem_and_tier(name)
    if paren is None:
        return None
    try:
        return _read_tier(paren, name)
    except FetchError as exc:
        raise _RowError(str(exc), _slug_base(stem)) from None


def _letterless(name: str) -> bool:
    """whether the name's stem (its tier paren dropped) carries no ASCII
    letter, so the row names no model any more than an empty cell does."""
    stem, _paren = _stem_and_tier(name)
    return _ASCII_LETTER_RE.search(stem) is None


def _fast_name_non_ascii(name: str) -> bool:
    """whether a fast-table name's stem holds a non-ASCII non-space
    character, so it names no model."""
    stem, _paren = _stem_and_tier(name)
    return any(not ch.isascii() and not ch.isspace() for ch in stem)


def split_name(name: str, url: str) -> tuple[str, tuple[str, int] | None]:
    """the public parse of a display name into (model id, tier); the module
    docstring owns the drop order, the tier read and the shape rule."""
    stem, paren = _stem_and_tier(name)
    if _SHAPE_RE.fullmatch(stem) is None:
        raise _name_shape_error(name, url, _shape_id(stem))
    slug = _slug_base(stem)
    if paren is None:
        return slug, None
    try:
        tier = _read_tier(paren, name)
    except FetchError as exc:
        raise _RowError(str(exc), slug) from None
    return slug, tier


_FOLDED_HEADER = [fold_heading(cell) for cell in TABLE_HEADER]


def model_table(text: str, url: str) -> list[list[str]]:
    """the "Model pricing" table; a missing table is a page-shape break."""
    for table in extract_markdown_tables(text):
        if table and [fold_heading(cell) for cell in table[0]] == _FOLDED_HEADER:
            return table
    raise FetchError(f"no model pricing table on {url}")


def check_row(row: list[str], url: str) -> None:
    if len(row) != len(TABLE_HEADER) or not row[0]:
        raise FetchError(f"row outside the pricing shape on {url}: {row!r}")


def detect(cfg: ProviderCfg) -> list[str]:
    text = fetch_text(cfg.detector_url)
    url = cfg.detector_url
    ids: list[str] = []
    seen: set[str] = set()
    for row in model_table(text, url)[2:]:
        try:
            check_row(row, url)
            slug, _tier = split_name(row[0], url)
        except FetchError as exc:
            log.warning("detect skip for %s: %s", cfg.key, exc)
            continue
        if slug not in seen:
            seen.add(slug)
            ids.append(slug)
    if not ids:
        raise FetchError(f"no model rows in the model pricing table on {url}")
    return ids
