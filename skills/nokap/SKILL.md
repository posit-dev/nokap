---
name: nokap
description: >
  Capture screenshots and PDFs from web pages using headless Chrome via CDP.
  Use when writing Python code that captures, screenshots, or renders web
  pages, local HTML files, or raw HTML strings to images or PDFs.
license: MIT
compatibility: Requires Python >=3.10 and Chrome/Chromium installed on the system.
---

# nokap

Capture screenshots and PDFs from web pages using headless Chrome via CDP.

## Installation

```bash
pip install nokap
```

Chrome or Chromium must be installed separately. nokap auto-discovers the
browser binary, or you can set `CHROME_PATH`.

## Decision Table

| Need | Use |
|------|-----|
| Screenshot a URL | `nokap.webshot(url, "out.png")` |
| Screenshot a local HTML file | `nokap.webshot("page.html", "out.png")` |
| Screenshot raw HTML string | `nokap.from_html(html_str, "out.png")` |
| Capture specific element | `nokap.webshot(url, "out.png", selector="table")` |
| High-resolution capture (2x) | `nokap.webshot(url, "out.png", zoom=2)` |
| Add padding around element | `nokap.webshot(url, "out.png", selector="h1", expand=10)` |
| Full-page PDF | `nokap.webshot(url, "out.pdf")` |
| Element-bounded PDF | `nokap.webshot(url, "out.pdf", selector="table")` |
| Capture from HTML to PDF | `nokap.from_html(html_str, "out.pdf", selector="table")` |
| Own a browser for a task | `with nokap.Renderer() as renderer:` |
| Clean up shared default renderer | `nokap.close()` |
| CLI screenshot | `nokap webshot URL file.png` |
| CLI from HTML file | `nokap from-html file.html out.png` |
| Check Chrome availability | `nokap doctor` or `nokap info` |

## Core API

### `webshot(url, file, *, ...)`

Main capture function. Output format determined by file extension (`.png`,
`.jpg`, `.webp`, `.pdf`).

Key parameters:

- `url`: URL or local file path (auto-converted to `file://`)
- `file`: Output path (default: `"webshot.png"`)
- `selector`: CSS selector to crop to element's bounding box
- `cliprect`: Explicit `(x, y, width, height)` clip rectangle
- `expand`: Padding around selector (int for all sides, or 4-tuple)
- `zoom`: Scale factor for raster images (>1 = higher resolution)
- `delay`: Seconds to wait after page load (default: 0.2)
- `vwidth` / `vheight`: Viewport dimensions (default: 992×744)
- `useragent`: Custom User-Agent string
- `renderer`: Borrow an existing `Renderer` without closing it

### `from_html(html, file, *, selector="html", encoding="utf-8", **kwargs)`

Render an HTML string to image or PDF. Writes HTML to a temp file and calls
`webshot()`. Accepts all `webshot()` keyword arguments.

### `Renderer(path=None, *, headless=True, extra_args=None, timeout=20, transport=None)`

Starts Chrome and connects immediately. Reuse its `webshot()` and `from_html()` methods, or pass it as `renderer=` to module functions. `renderer.browser` exposes the underlying `Chrome`. Browser environment settings are read at construction; use separate instances for independent tasks or settings.

Use a context manager or call `renderer.close()` to close its browser and connection. Closing is repeat-safe and final. A closed renderer or one whose browser has exited raises on capture; construct a new renderer to continue.

### `close()`

Close the shared default renderer used by module calls without `renderer=`. Explicit instances are unaffected. Called automatically at process exit.

## Gotchas

1. The module name is `nokap`, not `no-kap` or `no_kap`.
2. `selector` and `cliprect` are mutually exclusive: never pass both.
3. `zoom` only affects raster images (PNG/JPEG/WebP), not PDF output. PDFs are vector and always sharp.
4. `from_html()` defaults to `selector="html"` (full document), while `webshot()` defaults to `selector=None` (viewport only).
5. Module calls without `renderer=` create a shared default on first use, and replace it after it is closed or its browser exits. Explicit renderers do not restart their browser.
6. Local file paths are auto-converted to `file://` URLs: no manual conversion needed.
7. `expand` uses CSS pixel units and applies padding around the selector bounding box.
8. For wide elements (tables), nokap auto-detects intrinsic width and widens the viewport to avoid clipping.
9. Chrome must be installed separately: nokap does not bundle a browser.
10. Set `CHROME_PATH` environment variable if Chrome is not in a standard location.

## Error Handling

All nokap errors inherit from `NokapError`:

```python
import nokap

try:
    nokap.webshot("https://example.com", "out.png", selector="#missing")
except nokap.SelectorError:
    print("Element not found")
except nokap.PageLoadTimeout:
    print("Page took too long")
except nokap.ChromeNotFoundError:
    print("Install Chrome first")
except nokap.NokapError as e:
    print(f"Capture failed: {e}")
```

## Resources

- [Full documentation](https://posit-dev.github.io/nokap/)
- [llms.txt](https://posit-dev.github.io/nokap/llms.txt): API overview for LLMs
- [llms-full.txt](https://posit-dev.github.io/nokap/llms-full.txt): Complete reference
- [Source code](https://github.com/posit-dev/nokap)
