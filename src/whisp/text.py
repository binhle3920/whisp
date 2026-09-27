import re
from html import unescape

# Stops at whitespace and characters that commonly wrap a URL in prose or markup.
_URL = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"[ \t]+", " ", value).strip()


def html_links(value: str) -> list[str]:
    """Return absolute http(s) hrefs from HTML, which html_to_text would drop."""
    hrefs = re.findall(r"""(?i)href\s*=\s*["'](https?://[^"']+)["']""", value)
    return [unescape(href) for href in hrefs]


def find_urls(value: str) -> list[str]:
    """Return http(s) URLs in plain text, without trailing sentence punctuation."""
    return list(dict.fromkeys(url.rstrip(".,;:!?") for url in _URL.findall(value)))
