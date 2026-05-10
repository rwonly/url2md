#!/usr/bin/env python3
"""
url2md - Convert web pages to Markdown.

Supports:
- Single URL to Markdown conversion
- Batch conversion from a file containing URLs
- Custom output path or stdout
"""

from __future__ import annotations

import sys
import os
import argparse
import html
from typing import Optional
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser
from html.entities import name2codepoint
import re


def _strip_boilerplate_tags(html: str) -> str:
    """Remove script/style/noscript/template blocks before parsing."""
    for tag in ("script", "style", "noscript", "template"):
        html = re.sub(
            rf"<{tag}\b[^>]*>[\s\S]*?</{tag}\s*>",
            "",
            html,
            flags=re.IGNORECASE,
        )
    return html


def _extract_by_tag(html: str, tag: str) -> Optional[str]:
    """Return inner HTML of the first balanced <tag>...</tag> block, or None."""
    open_re = re.compile(rf"<\s*{tag}\b[^>]*>", re.IGNORECASE)
    close_re = re.compile(rf"<\s*/\s*{tag}\s*>", re.IGNORECASE)
    m = open_re.search(html)
    if not m:
        return None
    depth = 1
    pos = m.end()
    outer_start = m.end()
    while depth > 0 and pos < len(html):
        mo = open_re.search(html, pos)
        mc = close_re.search(html, pos)
        if not mc:
            return None
        if mo and mo.start() < mc.start():
            depth += 1
            pos = mo.end()
        else:
            depth -= 1
            if depth == 0:
                return html[outer_start : mc.start()]
            pos = mc.end()
    return None


def _extract_body(html: str) -> Optional[str]:
    m = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    if not m:
        return None
    start = m.end()
    m2 = re.search(r"</body\s*>", html[start:], re.IGNORECASE)
    if not m2:
        return html[start:]
    return html[start : start + m2.start()]


def _is_md_pipe_table_row(line: str) -> bool:
    """True if line looks like a GFM pipe table row (not HTML <table>)."""
    s = line.strip()
    if len(s) < 3:
        return False
    if not (s.startswith("|") and s.endswith("|")):
        return False
    # Need at least one interior cell boundary
    return s.count("|") >= 2


def _collapse_blank_lines_between_pipe_tables(md: str) -> str:
    """
    Many CMS pages put each markdown table row inside its own <p>, which produces
    blank lines between | ... | rows and breaks GFM table rendering. Remove those
    gaps while leaving code fences untouched.
    """
    lines = md.splitlines()
    n = len(lines)
    out: list[str] = []
    i = 0
    in_fence = False
    while i < n:
        line = lines[i]
        st = line.strip()
        if st.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue
        if _is_md_pipe_table_row(line):
            while out and out[-1] == "":
                out.pop()
            out.append(line)
            i += 1
            while i < n:
                ln = lines[i]
                lst = ln.strip()
                if lst.startswith("```"):
                    break
                if _is_md_pipe_table_row(ln):
                    out.append(ln)
                    i += 1
                elif lst == "":
                    j = i + 1
                    while j < n and lines[j].strip() == "":
                        j += 1
                    if j < n and _is_md_pipe_table_row(lines[j]):
                        i = j
                    else:
                        break
                else:
                    break
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _collapse_excess_blank_lines(md: str, max_consecutive_blank_lines: int = 1) -> str:
    """
    Collapse runs of empty lines (including whitespace-only) outside fenced code
    blocks so the file does not contain large vertical gaps.
    """
    lines = md.splitlines()
    out: list[str] = []
    in_fence = False
    blank_run = 0
    for line in lines:
        st = line.strip()
        if st.startswith("```"):
            in_fence = not in_fence
            blank_run = 0
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if st == "":
            blank_run += 1
            if blank_run <= max_consecutive_blank_lines:
                out.append("")
        else:
            blank_run = 0
            out.append(line)
    return "\n".join(out)


# Lines that are only a Markdown list marker (no item text), e.g. "-" or "12."
_EMPTY_MD_LIST_LINE = re.compile(
    r"^\s*(?:[-*+]|(?:\d{1,9}\.))\s*$",
)


def _strip_empty_markdown_list_lines(md: str) -> str:
    """
    Remove lines that are only a list marker (from empty <li> or layout quirks).
    Skips fenced code blocks.
    """
    lines = md.splitlines()
    out: list[str] = []
    in_fence = False
    for line in lines:
        st = line.strip()
        if st.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if _EMPTY_MD_LIST_LINE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


def prepare_html_document(html: str, full_page: bool = False) -> str:
    """
    Strip noisy tags, then prefer article/main/body so output matches
    reader-style tools that focus on primary content.
    """
    html = _strip_boilerplate_tags(html)
    if full_page:
        return _extract_body(html) or html
    frag = _extract_by_tag(html, "article") or _extract_by_tag(html, "main")
    if frag:
        return frag
    return _extract_body(html) or html


def extract_page_title(raw_html: str) -> str:
    """Prefer Open Graph title, then Twitter card, then <title>."""
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']',
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:title["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']*)["\']',
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']twitter:title["\']',
    ]
    for pat in patterns:
        m = re.search(pat, raw_html, re.IGNORECASE | re.DOTALL)
        if m:
            t = html.unescape(m.group(1).strip())
            t = re.sub(r"\s+", " ", t)
            if t:
                return t
    m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.DOTALL | re.IGNORECASE)
    if m:
        t = html.unescape(re.sub(r"\s+", " ", m.group(1).strip()))
        if t:
            return t
    return ""


class HTMLToMarkdown(HTMLParser):
    """HTML to Markdown using only the standard library."""

    def __init__(self, base_url: str = ""):
        super().__init__()
        self.base_url = base_url
        self.md: list[str] = []
        self.in_ignore = 0
        self.list_stack: list[str] = []  # 'ul' | 'ol'
        self.ol_index_stack: list[int] = []
        self.link_url: Optional[str] = None
        self.link_text: list[str] = []
        self.in_link = False
        self.header_level = 0
        self.skip_tags = {
            "script",
            "style",
            "nav",
            "aside",
            "footer",
            "noscript",
            "iframe",
            "canvas",
            "svg",
            "form",
            "button",
            "select",
            "textarea",
            "label",
            "title",
            "head",
            "template",
        }
        self.block_tags = {
            "p",
            "div",
            "section",
            "figure",
            "figcaption",
            "blockquote",
            "address",
        }
        self.pre_depth = 0
        self.pre_parts: list[str] = []
        self.pre_lang = ""
        self.inline_code_depth = 0
        self.bold_depth = 0
        self.em_depth = 0
        # Tables
        self.table_depth = 0
        self.table_rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.in_cell = False
        self.cell_parts: list[str] = []

    def _append_li_prefix(self) -> None:
        if not self.list_stack:
            return
        depth = max(0, len(self.list_stack) - 1)
        indent = "  " * depth
        if self.list_stack[-1] == "ul":
            marker = "- "
        else:
            if not self.ol_index_stack:
                return
            self.ol_index_stack[-1] += 1
            marker = f"{self.ol_index_stack[-1]}. "
        self.md.append(f"\n{indent}{marker}")

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag in self.skip_tags:
            self.in_ignore += 1
            return
        if self.in_ignore > 0:
            return

        if self.pre_depth > 0:
            if tag == "code":
                cls = attrs_dict.get("class") or ""
                for part in cls.split():
                    if part.startswith("language-"):
                        self.pre_lang = part.split("-", 1)[1]
                        break
            return

        if tag == "a":
            href = attrs_dict.get("href", "")
            if href:
                self.link_url = urljoin(self.base_url, href)
                self.in_link = True
                self.link_text = []
        elif tag == "img":
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "")
            if src:
                full_src = urljoin(self.base_url, src)
                self.md.append(f"![{alt}]({full_src})")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.header_level = int(tag[1])
        elif tag == "br":
            self.md.append("\n")
        elif tag == "hr":
            self.md.append("\n---\n")
        elif tag == "ul":
            self.list_stack.append("ul")
            self.ol_index_stack.append(0)
        elif tag == "ol":
            self.list_stack.append("ol")
            self.ol_index_stack.append(0)
        elif tag == "li":
            self._append_li_prefix()
        elif tag == "code":
            self.inline_code_depth += 1
            self.md.append("`")
        elif tag == "pre":
            self.pre_depth += 1
            if self.pre_depth == 1:
                self.pre_parts = []
                self.pre_lang = ""
        elif tag == "blockquote":
            self.md.append("\n> ")
        elif tag in ("strong", "b"):
            self.bold_depth += 1
            self.md.append("**")
        elif tag in ("em", "i"):
            self.em_depth += 1
            self.md.append("*")
        elif tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.table_rows = []
        elif tag == "tr":
            if self.table_depth == 1:
                self.current_row = []
        elif tag in ("th", "td"):
            if self.table_depth == 1:
                self.in_cell = True
                self.cell_parts = []
        elif tag in ("main", "article", "header"):
            self.md.append("\n")

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.in_ignore -= 1
            return
        if self.in_ignore > 0:
            return

        if self.pre_depth > 0:
            if tag == "pre":
                self.pre_depth -= 1
                if self.pre_depth == 0:
                    body = "".join(self.pre_parts).rstrip("\n")
                    lang = self.pre_lang or ""
                    fence = "```"
                    self.md.append(f"\n{fence}{lang}\n{body}\n{fence}\n")
                    self.pre_parts = []
                    self.pre_lang = ""
            return

        if tag == "a":
            if self.in_link and self.link_url:
                text = "".join(self.link_text).strip()
                if not text:
                    text = self.link_url
                if text == self.link_url:
                    self.md.append(text)
                else:
                    esc = text.replace("]", "\\]")
                    self.md.append(f"[{esc}]({self.link_url})")
            self.in_link = False
            self.link_url = None
            self.link_text = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.md.append("\n")
            self.header_level = 0
        elif tag in self.block_tags:
            self.md.append("\n\n")
        elif tag == "ul" or tag == "ol":
            if self.list_stack:
                self.list_stack.pop()
            if self.ol_index_stack:
                self.ol_index_stack.pop()
            self.md.append("\n")
        elif tag == "li":
            self.md.append("\n")
        elif tag == "code":
            if self.inline_code_depth > 0:
                self.inline_code_depth -= 1
                self.md.append("`")
        elif tag == "blockquote":
            self.md.append("\n")
        elif tag in ("strong", "b"):
            if self.bold_depth > 0:
                self.bold_depth -= 1
                self.md.append("**")
        elif tag in ("em", "i"):
            if self.em_depth > 0:
                self.em_depth -= 1
                self.md.append("*")
        elif tag == "table":
            if self.table_depth == 1:
                self._flush_table()
            self.table_depth = max(0, self.table_depth - 1)
        elif tag in ("th", "td"):
            if self.table_depth == 1:
                raw = "".join(self.cell_parts)
                cell = re.sub(r"\s+", " ", raw.strip())
                self.current_row.append(cell)
                self.in_cell = False
                self.cell_parts = []
        elif tag == "tr":
            if self.table_depth == 1 and self.current_row:
                self.table_rows.append(self.current_row)
                self.current_row = []
        elif tag in ("main", "article", "header"):
            self.md.append("\n")

    def _flush_table(self) -> None:
        rows = [r for r in self.table_rows if r]
        self.table_rows = []
        if not rows:
            self.md.append("\n")
            return
        ncol = max(len(r) for r in rows)

        def pad(row: list[str]) -> list[str]:
            out = row[:ncol]
            while len(out) < ncol:
                out.append("")
            return out

        def esc_cell(s: str) -> str:
            return s.replace("|", "\\|").replace("\n", " ").strip()

        rows = [pad(r) for r in rows]
        lines = ["", "| " + " | ".join(esc_cell(c) for c in rows[0]) + " |"]
        lines.append("| " + " | ".join(["---"] * ncol) + " |")
        for r in rows[1:]:
            lines.append("| " + " | ".join(esc_cell(c) for c in r) + " |")
        lines.append("")
        self.md.append("\n".join(lines))

    def handle_data(self, data):
        if self.in_ignore > 0:
            return

        if self.pre_depth > 0:
            self.pre_parts.append(data)
            return

        if self.in_cell and self.table_depth == 1:
            self.cell_parts.append(data)
            return

        if self.in_link:
            self.link_text.append(data)
            return

        text = data.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = text.replace("\n", " ")
        if not text.strip():
            return

        if self.header_level > 0:
            hashes = "#" * self.header_level
            self.md.append(f"\n{hashes} {text.strip()}\n")
            return

        self.md.append(text)

    def handle_entityref(self, name):
        try:
            char = chr(name2codepoint[name])
        except KeyError:
            char = f"&{name};"
        self.handle_data(char)

    def handle_charref(self, name):
        try:
            if name.startswith("x"):
                char = chr(int(name[1:], 16))
            else:
                char = chr(int(name))
        except (ValueError, OverflowError):
            char = f"&#{name};"
        self.handle_data(char)

    def get_markdown(self) -> str:
        md = "".join(self.md)
        md = re.sub(r"\n{3,}", "\n\n", md)
        md = _collapse_blank_lines_between_pipe_tables(md)
        md = _strip_empty_markdown_list_lines(md)
        md = _collapse_excess_blank_lines(md)
        return md.strip()


def fetch_url(url, timeout=30, user_agent=None):
    """Fetch HTML content from a URL."""
    if not user_agent:
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type.lower():
                part = content_type.lower().split("charset=")[-1]
                charset = part.split(";")[0].strip().strip('"').strip("'")

            html_bytes = response.read()
            try:
                html_str = html_bytes.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                html_str = html_bytes.decode("utf-8", errors="replace")
            return html_str
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP error {e.code}: {e.reason} for URL: {url}") from e
    except urllib.error.URLError as e:
        raise Exception(f"URL error: {e.reason} for URL: {url}") from e
    except Exception as e:
        raise Exception(f"Failed to fetch {url}: {str(e)}") from e


def url_to_markdown(url, title=True, timeout=30, full_page=False):
    """Convert a URL to Markdown."""
    raw_html = fetch_url(url, timeout=timeout)
    page_title = extract_page_title(raw_html) if title else ""

    fragment = prepare_html_document(raw_html, full_page=full_page)
    converter = HTMLToMarkdown(base_url=url)
    converter.feed(fragment)
    md = converter.get_markdown()

    if page_title:
        md_stripped = md.lstrip()
        if not md_stripped.startswith(f"# {page_title}"):
            md = f"# {page_title}\n\n{md}"

    return md


def batch_convert(urls_file, output_dir=None, full_page=False, title=True):
    """Convert multiple URLs from a file."""
    results = []
    errors = []

    with open(urls_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] Converting: {url}", file=sys.stderr)
        try:
            md = url_to_markdown(url, title=title, full_page=full_page)
            if output_dir:
                parsed = urlparse(url)
                filename = re.sub(r"[^a-zA-Z0-9]+", "-", parsed.netloc + parsed.path).strip("-")
                if not filename:
                    filename = f"url-{i}"
                filepath = os.path.join(output_dir, f"{filename}.md")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(md)
                results.append((url, filepath))
            else:
                results.append((url, md))
        except Exception as e:
            errors.append((url, str(e)))
            print(f"  ERROR: {e}", file=sys.stderr)

    return results, errors


def main():
    parser = argparse.ArgumentParser(
        description="Convert web pages to Markdown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://example.com/article
  %(prog)s https://example.com/page -o output.md
  %(prog)s -f urls.txt -d ./markdown_files/
        """,
    )
    parser.add_argument("url", nargs="?", help="URL to convert")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    parser.add_argument("-f", "--file", help="File containing URLs to convert (one per line)")
    parser.add_argument("-d", "--dir", help="Output directory for batch conversion")
    parser.add_argument("--no-title", action="store_true", help="Skip adding page title as H1")
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="Use full <body> instead of article/main extraction (more noise, wider coverage)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument("-v", "--version", action="version", version="%(prog)s 1.1.3")

    args = parser.parse_args()

    if args.file:
        if not os.path.exists(args.file):
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        if args.dir:
            os.makedirs(args.dir, exist_ok=True)
        results, errors = batch_convert(
            args.file,
            args.dir,
            full_page=args.full_page,
            title=not args.no_title,
        )
        if errors:
            print(
                f"\nCompleted with {len(errors)} errors out of {len(results) + len(errors)} URLs",
                file=sys.stderr,
            )
        else:
            print(f"\nSuccessfully converted all {len(results)} URLs", file=sys.stderr)
        sys.exit(0 if not errors else 1)

    if not args.url:
        parser.print_help()
        sys.exit(1)

    try:
        md = url_to_markdown(
            args.url,
            title=not args.no_title,
            timeout=args.timeout,
            full_page=args.full_page,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"Saved to: {args.output}")
        else:
            print(md)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
