# url2md

Convert web pages to clean, readable **Markdown** using a small Python script. Handy for documentation, archiving articles, batch exports, or any workflow where you want HTML turned into `.md` without pulling in third-party packages.

This repository also includes a **Cursor skill** ([`SKILL.md`](SKILL.md)) so agents can discover when to use url2md—for example when a single fetch is not enough and a script-based or bulk conversion fits better.

## Requirements

- **Python 3** (uses only the standard library: `urllib`, `html.parser`)

## Quick start

**Single URL** (prints Markdown to stdout):

```bash
python3 scripts/url2md.py https://example.com/article
```

**Save to a file:**

```bash
python3 scripts/url2md.py https://example.com/article -o article.md
```

**Batch conversion** — put one URL per line in a text file, then write each page into a directory:

```bash
python3 scripts/url2md.py -f urls.txt -d ./markdown_files/
```

## Features

- **No dependencies** beyond the Python standard library
- **Title extraction** — page title becomes a leading `#` heading (optional)
- **Link resolution** — relative URLs are turned into absolute ones
- **Basic formatting** — headings, paragraphs, lists, links, images, code blocks, tables
- **Noise removal** — strips scripts, styles, navigation, footers, and similar boilerplate

## CLI reference

| Option | Description |
|--------|-------------|
| `url` | Single URL to convert |
| `-o`, `--output` | Output file (default: stdout) |
| `-f`, `--file` | File containing URLs (one per line) |
| `-d`, `--dir` | Output directory for batch mode |
| `--no-title` | Do not add the page title as H1 |
| `--timeout` | Request timeout in seconds (default: 30) |
| `-v`, `--version` | Show version |

**More examples:**

```bash
python3 scripts/url2md.py https://docs.python.org/3
python3 scripts/url2md.py https://docs.python.org/3 -o python-docs.md
python3 scripts/url2md.py -f urls.txt -d ./output/ --timeout 60
python3 scripts/url2md.py https://example.com --no-title
```

## When to use it

- Turn documentation pages into Markdown for local reference
- Archive articles as plain text files
- Batch a list of URLs into separate files
- Prefer a script when interactive browser or fetch tools are not the right fit

## Limitations

- Only **static HTML** is converted; **JavaScript is not executed**
- Complex layouts (multi-column, heavy CSS) may not map cleanly to Markdown
- **Login or paywalled** pages need your own auth or cookies; the script does not log you in
- **Rate limits** or blocking by the remote site still apply to repeated requests

## License

[MIT-0](LICENSE) (MIT No Attribution).
