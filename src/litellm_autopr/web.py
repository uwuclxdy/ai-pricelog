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
