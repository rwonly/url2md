---
name: url2md
description: Convert web pages to Markdown format. Use when the user needs to: (1) Extract readable content from a URL and convert it to Markdown, (2) Batch convert multiple URLs to Markdown files, (3) Save web page content as .md for documentation, archiving, or note-taking. Works with any HTTP/HTTPS URL that returns HTML content. Also use when OpenClaw's web_fetch tool is insufficient and a script-based or bulk conversion approach is preferred.
---

# Url2md

Convert web pages to clean, readable Markdown.

## Quick Start

### Single URL

```bash
python3 scripts/url2md.py https://example.com/article
```

Output to a file:
```bash
python3 scripts/url2md.py https://example.com/article -o article.md
```

### Batch Conversion

Create a file with URLs (one per line):
```
https://example.com/article-1
https://example.com/article-2
https://example.com/article-3
```

Convert all and save to a directory:
```bash
python3 scripts/url2md.py -f urls.txt -d ./markdown_files/
```

## Features

- **No dependencies**: Uses only Python standard library (`urllib`, `html.parser`)
- **Title extraction**: Automatically adds page title as H1
- **Link resolution**: Converts relative URLs to absolute
- **Basic formatting**: Headings, paragraphs, lists, links, images, code blocks, tables
- **Noise removal**: Strips scripts, styles, navigation, footers, and other boilerplate

## Script Reference

### `scripts/url2md.py`

**Usage:**
```
url2md.py [url] [options]
```

**Options:**
| Option | Description |
|--------|-------------|
| `url` | Single URL to convert |
| `-o, --output` | Output file (default: stdout) |
| `-f, --file` | File containing URLs to convert |
| `-d, --dir` | Output directory for batch conversion |
| `--no-title` | Skip adding page title as H1 |
| `--timeout` | Request timeout in seconds (default: 30) |
| `-v, --version` | Show version |

**Examples:**
```bash
# Single URL to stdout
python3 scripts/url2md.py https://docs.python.org/3

# Save to file
python3 scripts/url2md.py https://docs.python.org/3 -o python-docs.md

# Batch with custom timeout
python3 scripts/url2md.py -f urls.txt -d ./output/ --timeout 60

# Skip title
python3 scripts/url2md.py https://example.com --no-title
```

## When to Use

- Converting documentation pages to Markdown for local reference
- Archiving web articles as text files
- Building static content from dynamic sources
- Extracting readable content when browser tools are unavailable
- Batch processing a list of URLs

## Limitations

- Converts static HTML only; does not execute JavaScript
- Complex layouts (multi-column, heavy CSS) may lose structural fidelity
- Login-required or paywalled content requires authentication tokens
- Rate-limited sites may block repeated requests
