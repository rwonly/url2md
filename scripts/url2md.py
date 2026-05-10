#!/usr/bin/env python3
"""
url2md - Convert web pages to Markdown.

Supports:
- Single URL to Markdown conversion
- Batch conversion from a file containing URLs
- Custom output path or stdout
"""

import sys
import os
import argparse
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser
from html.entities import name2codepoint
import re


class HTMLToMarkdown(HTMLParser):
    """A simple HTML to Markdown converter using only standard library."""

    def __init__(self, base_url=""):
        super().__init__()
        self.base_url = base_url
        self.md = []
        self.in_ignore = 0  # depth of tags to ignore (script, style, nav, etc.)
        self.list_stack = []  # track list types: 'ul' or 'ol'
        self.link_url = None
        self.link_text = []
        self.in_link = False
        self.header_level = 0
        self.last_tag = None
        self.skip_tags = {'script', 'style', 'nav', 'aside', 'footer', 'header',
                          'noscript', 'iframe', 'canvas', 'svg', 'form', 'button',
                          'select', 'textarea', 'label', 'title', 'head'}
        self.block_tags = {'p', 'div', 'section', 'article', 'main', 'figure',
                           'figcaption', 'blockquote', 'pre', 'address'}
        self.inline_skip = {'span', 'em', 'i', 'strong', 'b', 'mark', 'small',
                            'sub', 'sup', 'time', 'abbr', 'cite', 'dfn', 'kbd',
                            'samp', 'var', 'ruby', 'rt', 'rp', 'wbr'}

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self.last_tag = tag

        if tag in self.skip_tags:
            self.in_ignore += 1
            return

        if self.in_ignore > 0:
            return

        if tag == 'a':
            href = attrs_dict.get('href', '')
            if href:
                self.link_url = urljoin(self.base_url, href)
                self.in_link = True
                self.link_text = []
        elif tag == 'img':
            src = attrs_dict.get('src', '')
            alt = attrs_dict.get('alt', '')
            if src:
                full_src = urljoin(self.base_url, src)
                self.md.append(f'![{alt}]({full_src})')
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.header_level = int(tag[1])
        elif tag == 'br':
            self.md.append('\n')
        elif tag == 'hr':
            self.md.append('\n---\n')
        elif tag == 'ul':
            self.list_stack.append('ul')
        elif tag == 'ol':
            self.list_stack.append('ol')
        elif tag == 'li':
            pass  # handled in text with indentation
        elif tag == 'code':
            if attrs_dict.get('class', '').startswith('language-'):
                self.md.append('\n```\n')
            else:
                self.md.append('`')
        elif tag == 'pre':
            self.md.append('\n```\n')
        elif tag == 'blockquote':
            self.md.append('\n> ')
        elif tag == 'table':
            self.md.append('\n')
        elif tag == 'tr':
            self.md.append('\n')
        elif tag == 'th':
            self.md.append('| **')
        elif tag == 'td':
            self.md.append('| ')

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.in_ignore -= 1
            return

        if self.in_ignore > 0:
            return

        if tag == 'a':
            if self.in_link and self.link_url:
                text = ''.join(self.link_text).strip()
                if not text:
                    text = self.link_url
                # Don't add link if text equals url
                if text == self.link_url:
                    self.md.append(text)
                else:
                    self.md.append(f'[{text}]({self.link_url})')
            self.in_link = False
            self.link_url = None
            self.link_text = []
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.md.append('\n')
            self.header_level = 0
        elif tag in self.block_tags:
            self.md.append('\n\n')
        elif tag == 'ul' or tag == 'ol':
            if self.list_stack:
                self.list_stack.pop()
            self.md.append('\n')
        elif tag == 'li':
            self.md.append('\n')
        elif tag == 'code':
            self.md.append('`')
        elif tag == 'pre':
            self.md.append('```\n')
        elif tag == 'blockquote':
            self.md.append('\n')
        elif tag == 'th':
            self.md.append('** ')
        elif tag == 'td':
            self.md.append(' ')
        elif tag == 'table':
            self.md.append('\n')
        elif tag == 'p':
            self.md.append('\n\n')
        elif tag == 'br':
            self.md.append('\n')

    def handle_data(self, data):
        if self.in_ignore > 0:
            return

        text = data.strip()
        if not text:
            if self.in_link:
                self.link_text.append(data)
            return

        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text)

        if self.in_link:
            self.link_text.append(text)
            return

        # Add list markers
        if self.last_tag == 'li' and self.list_stack:
            depth = len(self.list_stack) - 1
            indent = '  ' * depth
            if self.list_stack[-1] == 'ul':
                marker = '- '
            else:
                marker = '1. '
            text = f'{indent}{marker}{text}'

        # Add header markers
        if self.header_level > 0:
            hashes = '#' * self.header_level
            text = f'\n{hashes} {text}\n'

        self.md.append(text)

    def handle_entityref(self, name):
        try:
            char = chr(name2codepoint[name])
        except KeyError:
            char = f'&{name};'
        self.handle_data(char)

    def handle_charref(self, name):
        try:
            if name.startswith('x'):
                char = chr(int(name[1:], 16))
            else:
                char = chr(int(name))
        except (ValueError, OverflowError):
            char = f'&#{name};'
        self.handle_data(char)

    def get_markdown(self):
        md = ''.join(self.md)
        # Clean up multiple newlines
        md = re.sub(r'\n{3,}', '\n\n', md)
        md = re.sub(r' +', ' ', md)
        return md.strip()


def fetch_url(url, timeout=30, user_agent=None):
    """Fetch HTML content from a URL."""
    if not user_agent:
        user_agent = 'Mozilla/5.0 (compatible; url2md/1.0)'

    headers = {
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
    }

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            # Detect encoding
            content_type = response.headers.get('Content-Type', '')
            charset = 'utf-8'
            if 'charset=' in content_type:
                charset = content_type.split('charset=')[-1].split(';')[0].strip()

            html_bytes = response.read()
            try:
                html = html_bytes.decode(charset, errors='replace')
            except (LookupError, UnicodeDecodeError):
                html = html_bytes.decode('utf-8', errors='replace')
            return html
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP error {e.code}: {e.reason} for URL: {url}")
    except urllib.error.URLError as e:
        raise Exception(f"URL error: {e.reason} for URL: {url}")
    except Exception as e:
        raise Exception(f"Failed to fetch {url}: {str(e)}")


def url_to_markdown(url, title=True, timeout=30):
    """Convert a URL to Markdown."""
    html = fetch_url(url, timeout=timeout)

    # Extract title
    page_title = ''
    if title:
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        if title_match:
            page_title = title_match.group(1).strip()
            page_title = re.sub(r'\s+', ' ', page_title)

    converter = HTMLToMarkdown(base_url=url)
    converter.feed(html)
    md = converter.get_markdown()

    if page_title:
        # Avoid duplicate title if content already starts with same heading
        md_stripped = md.lstrip()
        if not md_stripped.startswith(f"# {page_title}"):
            md = f"# {page_title}\n\n{md}"

    return md


def batch_convert(urls_file, output_dir=None):
    """Convert multiple URLs from a file."""
    results = []
    errors = []

    with open(urls_file, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] Converting: {url}", file=sys.stderr)
        try:
            md = url_to_markdown(url)
            if output_dir:
                # Create filename from URL
                parsed = urlparse(url)
                filename = re.sub(r'[^a-zA-Z0-9]+', '-', parsed.netloc + parsed.path).strip('-')
                if not filename:
                    filename = f'url-{i}'
                filepath = os.path.join(output_dir, f"{filename}.md")
                with open(filepath, 'w', encoding='utf-8') as f:
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
        description='Convert web pages to Markdown.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://example.com/article
  %(prog)s https://example.com/page -o output.md
  %(prog)s -f urls.txt -d ./markdown_files/
        """)
    parser.add_argument('url', nargs='?', help='URL to convert')
    parser.add_argument('-o', '--output', help='Output file (default: stdout)')
    parser.add_argument('-f', '--file', help='File containing URLs to convert (one per line)')
    parser.add_argument('-d', '--dir', help='Output directory for batch conversion')
    parser.add_argument('--no-title', action='store_true', help='Skip adding page title as H1')
    parser.add_argument('--timeout', type=int, default=30, help='Request timeout in seconds')
    parser.add_argument('-v', '--version', action='version', version='%(prog)s 1.0.0')

    args = parser.parse_args()

    # Batch mode
    if args.file:
        if not os.path.exists(args.file):
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        if args.dir:
            os.makedirs(args.dir, exist_ok=True)
        results, errors = batch_convert(args.file, args.dir)
        if errors:
            print(f"\nCompleted with {len(errors)} errors out of {len(results) + len(errors)} URLs", file=sys.stderr)
        else:
            print(f"\nSuccessfully converted all {len(results)} URLs", file=sys.stderr)
        sys.exit(0 if not errors else 1)

    # Single URL mode
    if not args.url:
        parser.print_help()
        sys.exit(1)

    try:
        md = url_to_markdown(args.url, title=not args.no_title, timeout=args.timeout)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(md)
            print(f"Saved to: {args.output}")
        else:
            print(md)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
