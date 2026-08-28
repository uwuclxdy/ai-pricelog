"""http fetch helpers: fetch_text, fetch_soup, and table extraction."""

from __future__ import annotations

import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup


class FetchError(Exception):
    """a fetch failed after retries; the message names the url."""


def fetch_text(url: str) -> str:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"url scheme must be http or https: {url!r}")
    try:
        with httpx.Client(
            transport=httpx.HTTPTransport(retries=3),
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed for {url}: {exc}") from exc


def fetch_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(fetch_text(url), "html.parser")


def extract_markdown_tables(text: str) -> list[list[list[str]]]:
    """split markdown pipe tables into row lists: header, separator, data rows."""
    blocks: list[list[str]] = []
    block: list[str] = []
    for line in text.splitlines():
        if "|" in line:
            block.append(line)
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    tables: list[list[list[str]]] = []
    for lines in blocks:
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
        if len(rows) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
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
