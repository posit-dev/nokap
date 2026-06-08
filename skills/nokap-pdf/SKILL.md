---
name: nokap-pdf
description: >
  Generate PDFs from web pages or HTML using nokap. Use when writing code that
  produces PDF output from URLs or HTML strings, configures paper sizes, margins,
  or creates element-bounded PDFs sized exactly to content.
license: MIT
compatibility: Requires Python >=3.10 and Chrome/Chromium installed on the system.
---

# nokap: PDF Generation

Generate PDFs from web pages, local HTML files, or raw HTML strings. nokap
supports two modes: full-page PDFs with standard paper dimensions, and
element-bounded PDFs sized exactly to a selected element.

## Two PDF Modes

| Mode | When to use | How to trigger |
|------|-------------|----------------|
| Full-page PDF | Reports, articles, printable pages | `webshot(url, "out.pdf")` |
| Element-bounded PDF | Tables, charts, widgets for embedding | `webshot(url, "out.pdf", selector="table")` |

The mode is automatically selected based on whether a `selector` (other than
`"html"`) or `cliprect` is provided.

## Full-Page PDF

Standard paper-sized PDF, like printing from the browser:

```python
import nokap

# Default: letter size, 0.5" margins
nokap.webshot("https://example.com", "page.pdf")

# A4 paper
nokap.webshot("https://example.com", "page.pdf", page_size="a4")

# Landscape orientation
nokap.webshot("https://example.com", "wide.pdf", landscape=True)

# Custom margins (inches): single value for all sides
nokap.webshot("https://example.com", "tight.pdf", margins=0.25)

# Asymmetric margins: (top, right, bottom, left) in inches
nokap.webshot("https://example.com", "report.pdf", margins=(1.0, 0.75, 1.0, 0.75))

# Print CSS backgrounds (colors, images)
nokap.webshot("https://example.com", "styled.pdf", print_background=True)
```

### Available Paper Sizes

| Size | Dimensions (inches) |
|------|---------------------|
| `"letter"` | 8.5 × 11 |
| `"legal"` | 8.5 × 14 |
| `"tabloid"` | 11 × 17 |
| `"ledger"` | 17 × 11 |
| `"a3"` | 11.7 × 16.5 |
| `"a4"` | 8.27 × 11.7 |
| `"a5"` | 5.83 × 8.27 |
| `"a6"` | 4.13 × 5.83 |

The `PaperSize` type is a `Literal` union of these values.

## Element-Bounded PDF

Creates a PDF sized exactly to the selected element. The text remains
selectable and the output is vector (resolution-independent). Perfect for
embedding tables or charts in presentations.

```python
import nokap

# PDF sized to a table element
nokap.webshot("https://example.com", "table.pdf", selector="table")

# PDF of a chart with padding
nokap.webshot("https://example.com", "chart.pdf", selector="#chart", expand=10)

# From raw HTML (Great Tables, Plotly, etc.)
nokap.from_html(table_html, "table.pdf", selector="table")

# With CSS backgrounds (important for styled tables)
nokap.from_html(table_html, "table.pdf", selector="table", print_background=True)
```

### When to Use Element-Bounded PDFs

- Embedding a single table in a LaTeX document or presentation
- Creating vector assets from HTML widgets
- Producing PDFs of exact content dimensions for design workflows
- Great Tables output for reports and slide decks

## HTML to PDF

```python
import nokap

# Full-page PDF from HTML string
html = "<html><body><h1>Report</h1><p>Content here.</p></body></html>"
nokap.from_html(html, "report.pdf", page_size="letter", margins=1.0)

# Element-bounded PDF from HTML
table_html = "<table>...</table>"
nokap.from_html(table_html, "table.pdf", selector="table", expand=5)

# Great Tables to PDF
import great_tables as gt

table = gt.GT(df).tab_header(title="Q4 Results")
nokap.from_html(table.as_raw_html(), "results.pdf", selector="table")
```

## PDF from Local Files

```python
import nokap

# Render a local HTML file to PDF
nokap.webshot("invoice.html", "invoice.pdf")

# With options
nokap.webshot("report.html", "report.pdf", page_size="a4", margins=0.75)

# Element from a local file
nokap.webshot("dashboard.html", "chart.pdf", selector="#revenue-chart")
```

## CLI for PDF Generation

```bash
# Full-page PDF
nokap webshot https://example.com page.pdf

# A4 paper size
nokap webshot https://example.com doc.pdf --page-size a4

# Landscape with backgrounds
nokap webshot report.html report.pdf --landscape --print-background

# Element-bounded PDF from HTML file
nokap from-html data.html table.pdf -s "table" -e 5
```

## Gotchas

1. `zoom` is ignored for PDF output. PDFs are vector format and always render at full resolution regardless of zoom setting.
2. `selector="html"` triggers full-page PDF mode (with paper dimensions). Any other selector triggers element-bounded mode.
3. Element-bounded PDFs use `print_background=True` by default (different from full-page PDFs which default to `False`).
4. Full-page PDF margins are in **inches**, while `expand` (for element-bounded PDFs) is in **CSS pixels**.
5. For HTML with dark backgrounds or colored table cells, always set `print_background=True` or the colors won't appear in the PDF.
6. The `margins` parameter only applies to full-page PDFs. For element-bounded PDFs, use `expand` to add spacing.
7. Paper size names are lowercase strings: `"letter"`, `"a4"`, `"legal"` (not `"Letter"` or `"A4"`).
8. Element-bounded PDFs have selectable text so they're true vector PDFs, not rasterized images wrapped in PDF.

## Decision Table

| Need | Code |
|------|------|
| Standard report PDF | `webshot(url, "out.pdf")` |
| A4 with narrow margins | `webshot(url, "out.pdf", page_size="a4", margins=0.25)` |
| Landscape PDF | `webshot(url, "out.pdf", landscape=True)` |
| Table as vector PDF | `webshot(url, "out.pdf", selector="table")` |
| Table PDF with styling | `from_html(html, "out.pdf", selector="table", print_background=True)` |
| Chart element as PDF | `webshot(url, "out.pdf", selector="#chart", expand=10)` |
| Printable with backgrounds | `webshot(url, "out.pdf", print_background=True)` |

## Resources

- [Full documentation](https://posit-dev.github.io/nokap/)
- [PDF generation guide](https://posit-dev.github.io/nokap/user-guide/12-pdf-generation.html)
- [llms-full.txt](https://posit-dev.github.io/nokap/llms-full.txt): complete reference
