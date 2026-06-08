from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from mcp.server import Server
from mcp.types import (
    Completion,
    CompletionArgument,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    PromptReference,
    Resource,
    ResourceTemplateReference,
    TextContent,
    Tool,
)
from pydantic import AnyUrl

from nokap._types import PaperSize

server = Server("nokap")
server.instructions = (
    "You are connected to the nokap MCP server for capturing screenshots and "
    "PDFs from web pages, local HTML files, or raw HTML strings using headless "
    "Chrome. Use `doctor` to verify Chrome is available before capturing. "
    "Use `screenshot_url` for live web pages, `screenshot_html` for raw HTML "
    "strings, and `generate_pdf` for PDF output."
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@server.list_tools()  # type: ignore[reportUntypedFunctionDecorator]
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="screenshot_url",
            description=(
                "Capture a screenshot of a web page or local HTML file. "
                "Returns the screenshot as a base64-encoded image and saves "
                "it to disk. Supports targeting specific elements via CSS "
                "selectors, viewport configuration, and zoom for high-DPI output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "URL to capture. Can be an http/https URL or a local "
                            "file path (automatically converted to file:// URL)."
                        ),
                    },
                    "file": {
                        "type": "string",
                        "description": (
                            "Output file path. Format determined by extension: "
                            ".png, .jpg, .webp. Defaults to 'screenshot.png'."
                        ),
                        "default": "screenshot.png",
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector to capture a specific element. The "
                            "screenshot is cropped to the element's bounding box."
                        ),
                    },
                    "vwidth": {
                        "type": "integer",
                        "description": "Viewport width in pixels.",
                        "default": 992,
                    },
                    "vheight": {
                        "type": "integer",
                        "description": "Viewport height in pixels.",
                        "default": 744,
                    },
                    "zoom": {
                        "type": "number",
                        "description": (
                            "Zoom/scale factor. Values > 1 produce higher "
                            "resolution images (e.g., 2 for Retina)."
                        ),
                        "default": 1,
                    },
                    "expand": {
                        "type": "integer",
                        "description": (
                            "Pixels to expand around the selector bounding box "
                            "(padding on all sides)."
                        ),
                        "default": 0,
                    },
                    "delay": {
                        "type": "number",
                        "description": (
                            "Seconds to wait after page load before capturing. "
                            "Increase for JavaScript-heavy pages."
                        ),
                        "default": 0.2,
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="screenshot_html",
            description=(
                "Capture a screenshot from a raw HTML string. Renders the HTML "
                "in a headless browser and captures the result. Ideal for "
                "converting generated HTML (from Great Tables, Plotly, custom "
                "templates) to images. Returns the file path of the saved image."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "html": {
                        "type": "string",
                        "description": "The HTML content to render and capture.",
                    },
                    "file": {
                        "type": "string",
                        "description": (
                            "Output file path. Format determined by extension: "
                            ".png, .jpg, .webp. Defaults to 'screenshot.png'."
                        ),
                        "default": "screenshot.png",
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector to capture. Defaults to 'html' (full "
                            "document). Use 'table', '.class', or '#id' to "
                            "capture specific elements."
                        ),
                        "default": "html",
                    },
                    "vwidth": {
                        "type": "integer",
                        "description": "Viewport width in pixels.",
                        "default": 992,
                    },
                    "vheight": {
                        "type": "integer",
                        "description": "Viewport height in pixels.",
                        "default": 744,
                    },
                    "zoom": {
                        "type": "number",
                        "description": (
                            "Zoom/scale factor. Values > 1 produce higher "
                            "resolution images."
                        ),
                        "default": 1,
                    },
                    "expand": {
                        "type": "integer",
                        "description": (
                            "Pixels to expand around the selector bounding box."
                        ),
                        "default": 0,
                    },
                    "delay": {
                        "type": "number",
                        "description": (
                            "Seconds to wait after page load before capturing."
                        ),
                        "default": 0.2,
                    },
                },
                "required": ["html"],
            },
        ),
        Tool(
            name="generate_pdf",
            description=(
                "Generate a PDF from a URL, local file, or raw HTML string. "
                "Supports full-page PDFs with standard paper sizes and "
                "element-bounded PDFs sized exactly to a selected element. "
                "Element-bounded PDFs preserve selectable text."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": (
                            "The content to convert to PDF. Can be: a URL "
                            "(http/https), a local file path, or raw HTML "
                            "string. The type is auto-detected."
                        ),
                    },
                    "file": {
                        "type": "string",
                        "description": "Output PDF file path.",
                        "default": "output.pdf",
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector for element-bounded PDF. When set to "
                            "a specific element (not 'html'), creates a PDF "
                            "sized exactly to that element."
                        ),
                    },
                    "page_size": {
                        "type": "string",
                        "description": (
                            "Paper size for full-page PDF. Options: letter, "
                            "legal, tabloid, a3, a4, a5, a6."
                        ),
                        "default": "letter",
                        "enum": [
                            "letter",
                            "legal",
                            "tabloid",
                            "ledger",
                            "a3",
                            "a4",
                            "a5",
                            "a6",
                        ],
                    },
                    "landscape": {
                        "type": "boolean",
                        "description": "Use landscape orientation.",
                        "default": False,
                    },
                    "margins": {
                        "type": "number",
                        "description": (
                            "Margins in inches (applied to all sides). "
                            "Only used for full-page PDFs."
                        ),
                        "default": 0.5,
                    },
                    "print_background": {
                        "type": "boolean",
                        "description": (
                            "Print CSS background colors and images. "
                            "Recommended for styled tables."
                        ),
                        "default": False,
                    },
                    "expand": {
                        "type": "integer",
                        "description": (
                            "Pixels of padding around element-bounded PDFs."
                        ),
                        "default": 0,
                    },
                    "vwidth": {
                        "type": "integer",
                        "description": "Viewport width in pixels.",
                        "default": 992,
                    },
                    "delay": {
                        "type": "number",
                        "description": (
                            "Seconds to wait after page load before generating."
                        ),
                        "default": 0.2,
                    },
                },
                "required": ["source"],
            },
        ),
        Tool(
            name="doctor",
            description=(
                "Check system readiness for captures. Verifies Chrome/Chromium "
                "is installed and accessible, reports the browser path and "
                "version, and performs a test capture to confirm everything works."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()  # type: ignore[reportUntypedFunctionDecorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "screenshot_url":
        return _handle_screenshot_url(arguments)
    elif name == "screenshot_html":
        return _handle_screenshot_html(arguments)
    elif name == "generate_pdf":
        return _handle_generate_pdf(arguments)
    elif name == "doctor":
        return _handle_doctor(arguments)
    raise ValueError(f"Unknown tool: {name}")


def _handle_screenshot_url(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle the screenshot_url tool."""
    import nokap

    url: str = arguments["url"]
    file: str = arguments.get("file", "screenshot.png")
    selector: str | None = arguments.get("selector")
    vwidth: int = arguments.get("vwidth", 992)
    vheight: int = arguments.get("vheight", 744)
    zoom: float = arguments.get("zoom", 1)
    expand: int = arguments.get("expand", 0)
    delay: float = arguments.get("delay", 0.2)

    try:
        result_path = nokap.webshot(
            url,
            file,
            selector=selector,
            vwidth=vwidth,
            vheight=vheight,
            zoom=zoom,
            expand=expand,
            delay=delay,
        )
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "status": "success",
                        "file": str(result_path),
                        "url": url,
                        "selector": selector,
                        "dimensions": f"{vwidth}x{vheight}",
                        "zoom": zoom,
                    }
                ),
            )
        ]
    except Exception as e:
        return [
            TextContent(
                type="text",
                text=json.dumps({"status": "error", "error": str(e)}),
            )
        ]
    finally:
        nokap.close()


def _handle_screenshot_html(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle the screenshot_html tool."""
    import nokap

    html: str = arguments["html"]
    file: str = arguments.get("file", "screenshot.png")
    selector: str = arguments.get("selector", "html")
    vwidth: int = arguments.get("vwidth", 992)
    vheight: int = arguments.get("vheight", 744)
    zoom: float = arguments.get("zoom", 1)
    expand: int = arguments.get("expand", 0)
    delay: float = arguments.get("delay", 0.2)

    try:
        result_path = nokap.from_html(
            html,
            file,
            selector=selector,
            vwidth=vwidth,
            vheight=vheight,
            zoom=zoom,
            expand=expand,
            delay=delay,
        )
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "status": "success",
                        "file": str(result_path),
                        "selector": selector,
                        "dimensions": f"{vwidth}x{vheight}",
                        "zoom": zoom,
                    }
                ),
            )
        ]
    except Exception as e:
        return [
            TextContent(
                type="text",
                text=json.dumps({"status": "error", "error": str(e)}),
            )
        ]
    finally:
        nokap.close()


def _handle_generate_pdf(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle the generate_pdf tool."""
    import nokap
    from nokap._utils import is_url

    source: str = arguments["source"]
    file: str = arguments.get("file", "output.pdf")
    selector: str | None = arguments.get("selector")
    page_size = cast(PaperSize, arguments.get("page_size", "letter"))
    landscape: bool = arguments.get("landscape", False)
    margins: float = arguments.get("margins", 0.5)
    print_background: bool = arguments.get("print_background", False)
    expand: int = arguments.get("expand", 0)
    vwidth: int = arguments.get("vwidth", 992)
    delay: float = arguments.get("delay", 0.2)

    try:
        # Determine if source is a URL/path or raw HTML
        is_html_string = not is_url(source) and not Path(source).exists()

        if is_html_string:
            result_path = nokap.from_html(
                source,
                file,
                selector=selector or "html",
                vwidth=vwidth,
                delay=delay,
                page_size=page_size,
                margins=margins,
                landscape=landscape,
                print_background=print_background,
                expand=expand,
            )
        else:
            result_path = nokap.webshot(
                source,
                file,
                selector=selector,
                vwidth=vwidth,
                delay=delay,
                page_size=page_size,
                margins=margins,
                landscape=landscape,
                print_background=print_background,
                expand=expand,
            )

        mode = "element-bounded" if (selector and selector != "html") else "full-page"
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "status": "success",
                        "file": str(result_path),
                        "mode": mode,
                        "page_size": page_size if mode == "full-page" else None,
                        "landscape": landscape,
                    }
                ),
            )
        ]
    except Exception as e:
        return [
            TextContent(
                type="text",
                text=json.dumps({"status": "error", "error": str(e)}),
            )
        ]
    finally:
        nokap.close()


def _handle_doctor(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle the doctor tool: system readiness check."""
    from nokap._browser import find_chrome
    from nokap._errors import ChromeNotFoundError

    results: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
    }

    # Check Chrome availability
    try:
        chrome_path = find_chrome()
        results["chrome_found"] = True
        results["chrome_path"] = str(chrome_path)

        # Try to get Chrome version
        try:
            version_output = subprocess.run(
                [str(chrome_path), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            results["chrome_version"] = version_output.stdout.strip()
        except Exception:
            results["chrome_version"] = "unknown"

    except ChromeNotFoundError:
        results["chrome_found"] = False
        results["chrome_path"] = None
        results["chrome_version"] = None

    # Test capture if Chrome is available
    if results["chrome_found"]:
        import nokap

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                test_file = Path(f.name)

            nokap.from_html(
                "<html><body><p>nokap test</p></body></html>",
                test_file,
            )
            results["test_capture"] = "success"
            results["test_file_size"] = test_file.stat().st_size
            test_file.unlink(missing_ok=True)
        except Exception as e:
            results["test_capture"] = "failed"
            results["test_error"] = str(e)
        finally:
            nokap.close()
    else:
        results["test_capture"] = "skipped (no Chrome)"

    is_ready = results.get("test_capture") == "success"
    results["status"] = "ready" if is_ready else "not ready"

    return [TextContent(type="text", text=json.dumps(results, indent=2))]


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@server.list_resources()  # type: ignore[reportUntypedFunctionDecorator]
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri=AnyUrl("nokap://capabilities"),
            name="Capture Capabilities",
            description=(
                "Summary of nokap's capture capabilities including supported "
                "output formats, paper sizes, and configuration options."
            ),
            mimeType="application/json",
        ),
    ]


@server.read_resource()  # type: ignore[reportUntypedFunctionDecorator]
async def read_resource(uri: AnyUrl) -> str:
    if str(uri) == "nokap://capabilities":
        return json.dumps(
            {
                "image_formats": ["png", "jpeg", "webp"],
                "pdf_paper_sizes": [
                    "letter",
                    "legal",
                    "tabloid",
                    "ledger",
                    "a0",
                    "a1",
                    "a2",
                    "a3",
                    "a4",
                    "a5",
                    "a6",
                ],
                "viewport_defaults": {"width": 992, "height": 744},
                "zoom_range": {"min": 0.1, "max": 10},
                "features": [
                    "CSS selector targeting",
                    "Element bounding box detection",
                    "Auto-detection of wide elements (tables)",
                    "High-DPI capture via zoom",
                    "Element-bounded vector PDFs",
                    "Full-page PDFs with paper sizes",
                    "Custom viewport dimensions",
                    "Page load delay for JavaScript content",
                    "Expand/padding around selectors",
                ],
            },
            indent=2,
        )
    raise ValueError(f"Unknown resource: {uri}")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@server.list_prompts()  # type: ignore[reportUntypedFunctionDecorator]
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="capture_strategy",
            description=(
                "Determine the best nokap capture approach for a given use case. "
                "Provides guidance on format, selector, zoom, delay, and other "
                "settings based on what you're trying to capture."
            ),
            arguments=[
                PromptArgument(
                    name="target",
                    description=(
                        "What you want to capture (e.g., 'a data table from "
                        "Great Tables', 'a full web page', 'a chart element')."
                    ),
                    required=True,
                ),
                PromptArgument(
                    name="output_use",
                    description=(
                        "How the output will be used (e.g., 'embed in a slide "
                        "deck', 'include in documentation', 'share on social "
                        "media', 'print at high quality')."
                    ),
                    required=False,
                ),
            ],
        ),
        Prompt(
            name="batch_capture",
            description=(
                "Generate a Python script for batch-capturing multiple pages "
                "or HTML outputs. Tailored to your specific data source and "
                "output requirements."
            ),
            arguments=[
                PromptArgument(
                    name="source_type",
                    description=(
                        "Type of content to capture in batch (e.g., 'list of "
                        "URLs', 'generated HTML tables', 'HTML files in a "
                        "directory')."
                    ),
                    required=True,
                ),
                PromptArgument(
                    name="output_format",
                    description=("Desired output format: png, jpg, webp, or pdf."),
                    required=True,
                ),
                PromptArgument(
                    name="naming",
                    description=(
                        "How to name output files (e.g., 'sequential numbers', "
                        "'based on URL', 'based on input filename')."
                    ),
                    required=False,
                ),
            ],
        ),
    ]


@server.get_prompt()  # type: ignore[reportUntypedFunctionDecorator]
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    if name == "capture_strategy":
        return GetPromptResult(messages=_prompt_capture_strategy(arguments or {}))
    elif name == "batch_capture":
        return GetPromptResult(messages=_prompt_batch_capture(arguments or {}))
    raise ValueError(f"Unknown prompt: {name}")


def _prompt_capture_strategy(arguments: dict[str, str]) -> list[PromptMessage]:
    """Generate guidance for the best capture approach."""
    target = arguments.get("target", "a web page")
    output_use = arguments.get("output_use", "general use")

    text = f"""Determine the best nokap capture approach for this use case:

**Target:** {target}
**Output use:** {output_use}

Consider these factors and provide specific recommendations:

1. **Format choice:**
   - PNG: Best for screenshots with transparency, UI captures, and general use
   - JPEG: Smaller files for photographs or complex images (no transparency)
   - WebP: Smallest files with good quality (modern format)
   - PDF: Vector output for print, presentations, or selectable text

2. **Function choice:**
   - `nokap.webshot(url, file)`: For live URLs or local files
   - `nokap.from_html(html_str, file)`: For HTML strings (Great Tables, Plotly)

3. **Selector strategy:**
   - No selector: Captures the viewport only
   - `selector="html"`: Captures the full document (handles scroll)
   - `selector="table"` / `selector=".class"` / `selector="#id"`: Element-bounded

4. **Quality settings:**
   - `zoom=2`: Retina/HiDPI quality (2x pixel density) (recommended for presentations)
   - `zoom=3`: Very high resolution for print
   - `zoom=1`: Standard screen resolution

5. **Timing:**
   - `delay=0.2`: Static pages (default)
   - `delay=1.0-2.0`: Pages with JavaScript rendering (charts, SPAs)
   - `delay=3.0+`: Heavy dashboards with lazy-loaded content

6. **PDF-specific:**
   - Element-bounded PDF (`selector="table"`): Exact size, vector, selectable
   - Full-page PDF (no selector or `selector="html"`): Standard paper with margins
   - `print_background=True`: Required for colored/styled tables

Provide a specific code example with the recommended settings for this use case."""

    return [PromptMessage(role="user", content=TextContent(type="text", text=text))]


def _prompt_batch_capture(arguments: dict[str, str]) -> list[PromptMessage]:
    """Generate a batch capture script template."""
    source_type = arguments.get("source_type", "list of URLs")
    output_format = arguments.get("output_format", "png")
    naming = arguments.get("naming", "sequential numbers")

    text = f"""Generate a Python script for batch capturing with nokap:

**Source:** {source_type}
**Output format:** {output_format}
**File naming:** {naming}

Requirements for the script:
- Import nokap at the top
- Call `nokap.close()` at the end to clean up Chrome
- Use appropriate error handling (try/except for NokapError)
- Print progress as each capture completes
- Use `zoom=2` for high-quality output unless the format is PDF
- For HTML strings, use `nokap.from_html()` with `selector="html"` or specific
- For URLs/files, use `nokap.webshot()`
- The browser stays alive between captures (no need to restart per item)
- For PDF output, consider using `print_background=True` for styled content

Generate a complete, runnable script."""

    return [PromptMessage(role="user", content=TextContent(type="text", text=text))]


# ---------------------------------------------------------------------------
# Completions
# ---------------------------------------------------------------------------

# Completion values for each prompt argument
_COMPLETIONS: dict[str, dict[str, list[str]]] = {
    "capture_strategy": {
        "target": [
            "a data table from Great Tables",
            "a full web page",
            "a Plotly chart",
            "a hero section or banner",
            "a navigation menu",
            "a dashboard with multiple charts",
            "an HTML email template",
            "a styled code snippet",
            "a social media card (Open Graph image)",
            "a PDF invoice or receipt",
        ],
        "output_use": [
            "embed in a slide deck",
            "include in documentation",
            "share on social media",
            "print at high quality",
            "use as a thumbnail",
            "embed in a PDF report",
            "attach to an email",
            "display in a README",
            "archive for compliance",
            "visual regression testing",
        ],
    },
    "batch_capture": {
        "source_type": [
            "list of URLs",
            "generated HTML tables from Great Tables",
            "HTML files in a directory",
            "Plotly figures",
            "Jinja2 templates with different data",
            "pages from a sitemap",
        ],
        "output_format": [
            "png",
            "jpg",
            "webp",
            "pdf",
        ],
        "naming": [
            "sequential numbers (001, 002, ...)",
            "based on URL slug",
            "based on input filename",
            "timestamp-based",
            "custom prefix with index",
        ],
    },
}


@server.completion()  # type: ignore[reportUntypedFunctionDecorator]
async def handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: Any | None = None,
) -> Completion | None:
    """Provide auto-complete suggestions for prompt arguments."""
    # Only handle prompt completions
    if not isinstance(ref, PromptReference):
        return None

    prompt_name = ref.name
    arg_name = argument.name
    prefix = argument.value.lower()

    # Look up completions for this prompt + argument
    prompt_completions = _COMPLETIONS.get(prompt_name)
    if not prompt_completions:
        return None

    all_values = prompt_completions.get(arg_name)
    if not all_values:
        return None

    # Filter by prefix if the user has typed something
    if prefix:
        matches = [v for v in all_values if v.lower().startswith(prefix)]
        # Also include partial matches (contains) if few startswith matches
        if len(matches) < 3:
            contains = [
                v for v in all_values if prefix in v.lower() and v not in matches
            ]
            matches.extend(contains)
    else:
        matches = all_values

    return Completion(
        values=matches[:20],
        total=len(matches),
        hasMore=len(matches) > 20,
    )
