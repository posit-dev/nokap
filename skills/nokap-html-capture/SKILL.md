---
name: nokap-html-capture
description: >
  Capture screenshots and PDFs from raw HTML strings or local HTML files using
  nokap. Use when rendering HTML output from packages like Great Tables, Plotly,
  or custom report generators to images or PDFs.
license: MIT
compatibility: Requires Python >=3.10 and Chrome/Chromium installed on the system.
---

# nokap: HTML Capture

Render raw HTML strings or local HTML files to images (PNG, JPEG, WebP) or PDFs.
This is the primary integration point for packages that generate HTML and need
to convert it to a visual format.

## `from_html()`: Core Function

```python
import nokap

html = "<h1>Hello World</h1><p>Rendered by nokap</p>"
nokap.from_html(html, "output.png")
```

Key differences from `webshot()`:

- Accepts an HTML string directly (no need to write a file manually)
- Defaults to `selector="html"` (captures the full document, not just viewport)
- Manages temp file creation and cleanup internally

## Capturing Generated HTML

### Great Tables Integration

```python
import great_tables as gt
import nokap

# Build a table
table = gt.GT(df).tab_header(title="Sales Report")

# Get the HTML and capture it
html = table.as_raw_html()
nokap.from_html(html, "table.png", selector="table", zoom=2, expand=10)
```

### Plotly Integration

```python
import plotly.express as px
import nokap

fig = px.scatter(df, x="x", y="y", title="My Chart")
html = fig.to_html(include_plotlyjs="cdn")
nokap.from_html(html, "chart.png", selector=".plotly-graph-div", delay=1.0)
```

### Custom HTML

```python
import nokap

html = """
<!DOCTYPE html>
<html>
<head>
  <style>
    .card { padding: 20px; border: 1px solid #ddd; border-radius: 8px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Status: Active</h2>
    <p>All systems operational.</p>
  </div>
</body>
</html>
"""
nokap.from_html(html, "card.png", selector=".card", expand=5)
```

## Selector Strategies for HTML Capture

| HTML Structure | Selector | Notes |
|----------------|----------|-------|
| Full document | `"html"` (default) | Captures everything |
| A single table | `"table"` | Element-bounded capture |
| Table by class | `"table.gt_table"` | Great Tables default class |
| Div by ID | `"#my-chart"` | Plotly containers, custom widgets |
| First match | `".card"` | Takes first matching element |
| Body content | `"body"` | Excludes html margins |

## Controlling Output Size

```python
# Natural width: nokap auto-detects wide elements (tables, charts)
# and expands the viewport to avoid clipping
nokap.from_html(wide_table_html, "table.png", selector="table")

# Force a specific viewport width
nokap.from_html(html, "narrow.png", vwidth=600)

# High-resolution output
nokap.from_html(html, "sharp.png", selector="table", zoom=2)

# Padding around element
nokap.from_html(html, "padded.png", selector=".widget", expand=15)

# Asymmetric padding: (top, right, bottom, left)
nokap.from_html(html, "padded.png", selector=".widget", expand=(5, 10, 5, 10))
```

## HTML to PDF

```python
# Element-bounded PDF (sized exactly to the element)
nokap.from_html(html, "table.pdf", selector="table")

# Full-page PDF with standard paper size
nokap.from_html(html, "report.pdf", selector="html", page_size="letter")

# Landscape PDF
nokap.from_html(html, "wide.pdf", selector="html", landscape=True)

# PDF with CSS backgrounds printed
nokap.from_html(html, "styled.pdf", selector="table", print_background=True)
```

## Encoding

```python
# Default UTF-8
nokap.from_html(html, "out.png")

# Explicit encoding for non-UTF-8 content
nokap.from_html(html, "out.png", encoding="latin-1")
```

nokap auto-injects a `<meta charset>` tag if one is not present in the HTML.

## Batch HTML Capture

```python
import nokap

tables = [generate_table(data) for data in datasets]

for i, html in enumerate(tables):
    nokap.from_html(html, f"table_{i}.png", selector="table", zoom=2)

nokap.close()
```

## Capturing Local HTML Files

For existing HTML files on disk, use `webshot()` with a file path:

```python
import nokap

# String path
nokap.webshot("report.html", "report.png", selector="table")

# pathlib.Path
from pathlib import Path
nokap.webshot(Path("output/chart.html"), "chart.png")
```

To read a file and use `from_html()` instead (useful when you want to
modify the HTML first):

```python
from pathlib import Path
import nokap

html = Path("template.html").read_text()
html = html.replace("{{TITLE}}", "My Report")
nokap.from_html(html, "report.png")
```

## CLI for HTML Files

```bash
# Render a local HTML file
nokap from-html report.html report.png

# With selector and zoom
nokap from-html data.html table.png -s "table" -z 2

# With padding
nokap from-html gt_table.html table.png -s "table" -e 10

# To PDF
nokap from-html invoice.html invoice.pdf -s "table"
```

## Gotchas

1. `from_html()` defaults to `selector="html"`; it captures the full document, not just the viewport. This differs from `webshot()` which defaults to `selector=None` (viewport-only).
2. The HTML is written to a temp file and loaded via `file://`. External resources using relative paths won't resolve unless you use absolute URLs or inline styles.
3. For HTML with external CSS/JS (CDN links), add `delay=1.0` or more to allow resources to load.
4. nokap auto-detects wide elements (tables wider than viewport) and expands the viewport. You generally don't need to set `vwidth` manually for tables.
5. `zoom` does not affect PDF output. PDFs are vector format and always render at full resolution.
6. If your HTML references local images with relative paths, use `webshot()` with the HTML file path instead of `from_html()` with the string, so relative paths resolve correctly.

## Resources

- [Full documentation](https://posit-dev.github.io/nokap/)
- [Screenshots guide](https://posit-dev.github.io/nokap/user-guide/10-screenshots.html)
- [Quick start](https://posit-dev.github.io/nokap/user-guide/02-quick-start.html)
