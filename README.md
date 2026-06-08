<div align="center">

# nokap

_Screenshots and PDFs from web pages. Powered by headless Chrome._

[![Python Versions](https://img.shields.io/pypi/pyversions/nokap.svg)](https://pypi.org/project/nokap/)
[![PyPI](https://img.shields.io/pypi/v/nokap?logo=python&logoColor=white&color=orange)](https://pypi.org/project/nokap/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://choosealicense.com/licenses/mit/)
[![CI](https://github.com/posit-dev/nokap/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/posit-dev/nokap/actions/workflows/ci.yml)

</div>

**nokap** captures screenshots and PDFs from web pages (or local HTML) using headless Chrome via the [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/). It doesn't need Selenium or Playwright. We use just one lightweight dependency (`websockets`).

## Installation

```bash
pip install nokap
```

Chrome or Chromium must be installed on the system. **nokap** will hunt it down pretty quickly.

## Quick Start

```python
import nokap

# Screenshot a URL
nokap.webshot("https://example.com", "example.png")

# Save as PDF
nokap.webshot("https://example.com", "example.pdf")

# Screenshot with a CSS selector (captures just that element)
nokap.webshot("https://example.com", "header.png", selector="h1")

# From an HTML string (great for table libraries)
nokap.from_html("<h1>Hello, world!</h1>", "hello.png")
```

## API

### `nokap.webshot()`

Take a screenshot or PDF of a web page.

```python
nokap.webshot(
    url,                # URL or local file path
    file="webshot.png", # Output path (.png, .jpg, .webp, .pdf)
    *,
    vwidth=992,         # Viewport width (px)
    vheight=744,        # Viewport height (px)
    selector=None,      # CSS selector to capture
    cliprect=None,      # Clip rectangle (x, y, width, height)
    expand=0,           # Padding around selector (px)
    delay=0.2,          # Wait after page load (seconds)
    zoom=1,             # Scale factor (2 = retina)
    useragent=None,     # Custom User-Agent string
)
```

### `nokap.from_html()`

Render an HTML string to an image or PDF. Designed for integration with table/report libraries.

```python
nokap.from_html(
    html,               # HTML content
    file="webshot.png", # Output path
    *,
    selector="html",    # CSS selector to capture
    **kwargs,           # All webshot() options
)
```

### `nokap.close()`

Shut down the background Chrome process. Called automatically at exit, but available for explicit cleanup.

```python
nokap.close()
```

## How It Works

nokap communicates directly with Chrome over the [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/) via WebSockets. No browser driver binaries, no heavyweight automation frameworks.

The architecture:

1. **Launch**: Finds and starts headless Chrome with a random debugging port
2. **Connect**: Opens a WebSocket to Chrome's CDP endpoint
3. **Capture**: Creates a tab, navigates, waits, then calls `Page.captureScreenshot` or `Page.printToPDF`
4. **Cleanup**: Closes the tab; Chrome stays running for reuse until `nokap.close()` or process exit

## Features

| Feature | Details |
|---------|---------|
| **Image formats** | PNG, JPEG, WebP |
| **PDF generation** | Configurable page size, margins, orientation |
| **CSS selectors** | Capture specific elements (or union of multiple) |
| **Zoom/scale** | Produce retina-quality (2×, 3×) images |
| **Expand/padding** | Add whitespace around captured elements |
| **Local HTML** | Render HTML strings or local `.html` files |
| **Viewport control** | Set width/height for responsive layouts |
| **Custom User-Agent** | Override the browser UA string |
| **Auto-cleanup** | Chrome process managed via `atexit` |
| **Jupyter-safe** | Works in notebooks (no event loop conflicts) |

## Configuration

| Environment Variable | Purpose |
|---------------------|---------|
| `CHROME_PATH` | Override Chrome binary location |

## Requirements

- Python ≥ 3.10
- Chrome or Chromium installed on the system

## License

MIT
