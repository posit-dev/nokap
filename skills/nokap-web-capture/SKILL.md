---
name: nokap-web-capture
description: >
  Capture screenshots from live web pages using nokap. Use when writing code
  that screenshots URLs, configures viewports, handles page load timing, or
  captures specific page elements from remote sites.
license: MIT
compatibility: Requires Python >=3.10, Chrome/Chromium, and network access for remote URLs.
---

# nokap: Web Page Capture

Capture screenshots and PDFs from live web pages (HTTP/HTTPS URLs) or local
HTML files served via `file://`.

## Basic Capture

```python
import nokap

# Screenshot a web page
nokap.webshot("https://example.com", "page.png")

# JPEG output (determined by extension)
nokap.webshot("https://example.com", "page.jpg")

# WebP output
nokap.webshot("https://example.com", "page.webp")
```

## Viewport Configuration

Control the browser viewport to simulate different devices or layouts:

```python
# Desktop (default: 992×744)
nokap.webshot("https://example.com", "desktop.png")

# Mobile viewport
nokap.webshot("https://example.com", "mobile.png", vwidth=375, vheight=812)

# Tablet viewport
nokap.webshot("https://example.com", "tablet.png", vwidth=768, vheight=1024)

# Wide viewport for dashboards
nokap.webshot("https://example.com", "wide.png", vwidth=1920, vheight=1080)
```

## High-Resolution Captures

Use `zoom` to produce Retina/HiDPI screenshots:

```python
# 2x resolution (double pixel density)
nokap.webshot("https://example.com", "retina.png", zoom=2)

# 3x for very sharp icons/logos
nokap.webshot("https://example.com", "logo.png", selector=".logo", zoom=3)
```

The output image dimensions are multiplied by the zoom factor (e.g., a 992px
viewport at zoom=2 produces a 1984px-wide image).

## Element Selection

Target specific page elements with CSS selectors:

```python
# Capture just the header
nokap.webshot("https://example.com", "header.png", selector="header")

# Capture a specific element by ID
nokap.webshot("https://example.com", "chart.png", selector="#main-chart")

# Capture by class
nokap.webshot("https://example.com", "nav.png", selector=".navbar")

# Add padding around the element
nokap.webshot("https://example.com", "card.png", selector=".card", expand=20)

# Asymmetric padding: (top, right, bottom, left)
nokap.webshot(
    "https://example.com", "hero.png",
    selector=".hero",
    expand=(10, 20, 10, 20),
)
```

## Page Load Timing

Control when the capture happens relative to page load:

```python
# Default: 0.2s delay after load event
nokap.webshot("https://example.com", "page.png")

# Longer delay for heavy JavaScript (SPAs, charts, animations)
nokap.webshot("https://example.com", "dashboard.png", delay=3.0)

# Minimal delay for static pages
nokap.webshot("https://example.com", "static.png", delay=0)

# Very long delay for pages with lazy-loaded content
nokap.webshot("https://example.com", "lazy.png", delay=5.0)
```

## Custom User-Agent

Spoof the browser identity for responsive sites or bot detection:

```python
# Mobile User-Agent for responsive content
nokap.webshot(
    "https://example.com", "mobile.png",
    vwidth=375, vheight=812,
    useragent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) ...",
)
```

## Explicit Clip Rectangles

Capture an exact pixel region (alternative to selectors):

```python
# Capture a 400×300 region starting at (100, 50)
nokap.webshot(
    "https://example.com", "region.png",
    cliprect=(100, 50, 400, 300),
)
```

Note: `cliprect` and `selector` are mutually exclusive.

## Batch Captures

For multiple captures, the browser stays alive between calls:

```python
import nokap

urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3",
]

for i, url in enumerate(urls):
    nokap.webshot(url, f"page_{i}.png")

# Clean up when done
nokap.close()
```

## Local File Capture

Local HTML files work the same way and nokap auto-converts paths to `file://`:

```python
# Path string
nokap.webshot("report.html", "report.png")

# pathlib.Path
from pathlib import Path
nokap.webshot(Path("output/chart.html"), "chart.png")
```

## CLI Usage

```bash
# Basic screenshot
nokap webshot https://example.com page.png

# With options
nokap webshot https://example.com hero.png -s "h1" -z 2 -e 10

# Mobile viewport
nokap webshot https://example.com mobile.png --vwidth 375 --vheight 812

# Longer delay for SPAs
nokap webshot https://example.com app.png -d 3.0
```

## Gotchas

1. The `delay` parameter counts from the page load event, not from navigation start. JavaScript that runs after `load` may need a longer delay.
2. Selectors must match exactly one element. If the selector matches nothing, `SelectorError` is raised.
3. `zoom` multiplies the pixel dimensions so a 992×744 viewport at zoom=2 produces a 1984×1488 image file.
4. Wide elements (e.g., tables) are auto-detected. nokap temporarily widens the viewport to capture the full natural width without horizontal clipping.
5. For pages behind authentication, nokap cannot handle login flows. Pre-authenticate or use a session cookie via a custom user-agent workaround.

## Resources

- [Full documentation](https://posit-dev.github.io/nokap/)
- [Screenshots guide](https://posit-dev.github.io/nokap/user-guide/10-screenshots.html)
- [Selectors guide](https://posit-dev.github.io/nokap/user-guide/11-selectors-and-clipping.html)
