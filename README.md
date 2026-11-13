<div align="center">

# nokap

_Screenshots and PDFs from web pages. Powered by headless Chrome._

[![Python Versions](https://img.shields.io/pypi/pyversions/nokap.svg)](https://pypi.org/project/nokap/)
[![PyPI](https://img.shields.io/pypi/v/nokap?logo=python&logoColor=white&color=orange)](https://pypi.org/project/nokap/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://choosealicense.com/licenses/mit/)
[![CI](https://github.com/posit-dev/nokap/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/posit-dev/nokap/actions/workflows/ci.yml)

</div>

**nokap** captures screenshots and PDFs from web pages (or local HTML) using headless Chrome via the [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/). It doesn't need Selenium or Playwright. Its only runtime dependencies are `websockets` and `click`.

## Installation

```bash
pip install nokap
```

**nokap** uses the Chrome or Chromium already on your system and will hunt it down pretty quickly. If you don't have one, or you're running inside a sandbox where full Chrome can't start (such as a coding agent's sandbox on macOS), install Chrome's standalone headless build:

```bash
nokap install-chrome
```

This downloads `chrome-headless-shell` from [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/) into nokap's cache, and nokap uses it from then on. Nothing is downloaded unless you run this command. Check your setup with `nokap doctor`.

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
    renderer=None,      # Use an existing Renderer
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
    renderer=None,      # Use an existing Renderer
    **kwargs,           # All webshot() options
)
```

### `nokap.Renderer()`

Own a browser and its CDP connection explicitly. Construction starts Chrome and connects immediately:

```python
with nokap.Renderer(extra_args=["--lang=de"]) as renderer:
    renderer.webshot("https://example.com", "example.png")
    nokap.from_html("<h1>Hello</h1>", "hello.png", renderer=renderer)
    print(renderer.browser.transport)
```

The constructor is `Renderer(path=None, *, headless=True, extra_args=None, timeout=20, transport=None)`. Its `webshot()` and `from_html()` methods accept the same capture options as the module functions. `renderer.browser` exposes the underlying `Chrome`, including its `pid` and `transport`.

Reuse one renderer for a batch. Use separate instances for independent tasks or browser settings. Each browser gets its own temporary profile by default. Passing `renderer=` to a module function borrows the instance; the caller remains responsible for closing it.

Leaving the `with` block closes the browser and connection. You can also call `renderer.close()` explicitly; repeated calls are safe. Closing is final: captures on a closed renderer or one whose browser has exited raise an error. Construct a new renderer to continue.

### `nokap.close()`

Close the shared default renderer used by module calls without `renderer=`. Explicitly constructed renderers are unaffected. The next convenience call creates a new default renderer; it also replaces a default whose browser has exited. Cleanup runs automatically at process exit.

```python
nokap.close()
```

### `nokap.install_chrome()`

Download `chrome-headless-shell` into nokap's cache and return its path. Same as `nokap install-chrome` on the command line.

```python
nokap.install_chrome(
    version="stable",   # Channel (stable/beta/dev/canary), milestone ("156"), or exact version
    *,
    force=False,        # Reinstall even if already present
)
```

## How It Works

nokap communicates directly with Chrome over the [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/), using pipes by default on macOS and Linux and WebSockets on Windows. No browser driver binaries, no heavyweight automation frameworks.

The architecture:

1. **Launch**: Finds and starts headless Chrome with pipes or a debugging port
2. **Connect**: Opens the connection to Chrome's CDP endpoint
3. **Capture**: Creates a tab, navigates, waits, then calls `Page.captureScreenshot` or `Page.printToPDF`
4. **Cleanup**: Closes the tab; Chrome stays running for reuse until its renderer is closed or the process exits

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
| **Sandbox-friendly** | Runs in macOS agent sandboxes with `chrome-headless-shell` |

## Browser Discovery

nokap uses the first browser it finds, in this order:

1. `CHROME_PATH`
2. `chrome-headless-shell` installed by `nokap install-chrome`
3. `chrome-headless-shell` on `PATH`
4. Chrome, Chromium, or another Chromium-based browser (such as Edge) in its standard install location

## Configuration

| Environment Variable | Purpose |
|---------------------|---------|
| `CHROME_PATH` | Override Chrome binary location |
| `NOKAP_TRANSPORT` | Override CDP transport: `pipe` (default on macOS/Linux) or `websocket` (default on Windows) |
| `NOKAP_CHROME_ARGS` | Extra Chrome command-line flags for every launch (shell-style quoting) |
| `NOKAP_CACHE_DIR` | Where `nokap install-chrome` stores browsers |

To use WebSockets explicitly on macOS or Linux:

```bash
NOKAP_TRANSPORT=websocket python render.py
```

In pipe mode, nokap starts Chrome with `--remote-debugging-pipe`. CDP commands and responses use inherited file descriptors, so nokap does not open a listening TCP port or connect to one. This also applies to libraries that call nokap, including Great Tables' `GT.gtsave()`. Both transports use a separate temporary profile for each browser unless `--user-data-dir` is supplied explicitly.

The sandbox must still allow the selected browser to start and write temporary files. For MCP Console on macOS, install `chrome-headless-shell` with `nokap install-chrome` outside the sandbox. nokap uses pipes automatically and selects `--single-process` if the required macOS user-directory lookups fail with an I/O error. It also retries with `--single-process` when Chrome reports a Mach service registration denial. See the [MCP Console example](user_guide/23-ai-agent-integration.qmd#mcp-console) for returning a Great Tables table as an MCP image without changing sandbox permissions.

Configuration is read once when a renderer is constructed. Later environment changes do not reconfigure that instance. Construct another renderer for different settings, or call `nokap.close()` to reset the shared default. For `Renderer` and `Chrome`, explicit `transport=` overrides `NOKAP_TRANSPORT`; `extra_args=` are appended after `NOKAP_CHROME_ARGS`.

`Chrome.port` and `Chrome.ws_url` require WebSocket transport. Use `Renderer(transport="websocket")` and access them through `renderer.browser`, or construct `Chrome(transport="websocket")` directly. Pipe transport requires POSIX and is not supported on Windows.

## Requirements

- Python ≥ 3.10
- Chrome or Chromium installed on the system, or `chrome-headless-shell` installed with `nokap install-chrome`

## License

MIT
