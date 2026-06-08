from nokap._types import ClipRect, Expand, PDFOptions
from nokap._pdf import _apply_expand


def test_clip_rect_to_cdp():
    clip = ClipRect(x=10, y=20, width=100, height=200)
    cdp = clip.to_cdp()
    assert cdp == {"x": 10, "y": 20, "width": 100, "height": 200, "scale": 1.0}


def test_clip_rect_with_scale():
    clip = ClipRect(x=0, y=0, width=50, height=50, scale=2.0)
    assert clip.to_cdp()["scale"] == 2.0


def test_expand_from_single_int():
    exp = Expand.from_value(5)
    assert exp.top == 5
    assert exp.right == 5
    assert exp.bottom == 5
    assert exp.left == 5


def test_expand_from_tuple():
    exp = Expand.from_value((1, 2, 3, 4))
    assert exp.top == 1
    assert exp.right == 2
    assert exp.bottom == 3
    assert exp.left == 4


def test_pdf_options_from_page_size_letter():
    opts = PDFOptions.from_page_size("letter")
    assert opts.paper_width == 8.5
    assert opts.paper_height == 11.0
    assert opts.margin_top == 0.5


def test_pdf_options_from_page_size_a4_landscape():
    opts = PDFOptions.from_page_size("a4", landscape=True)
    assert opts.paper_width == 11.7
    assert opts.paper_height == 8.27
    assert opts.landscape is True


def test_pdf_options_to_cdp():
    opts = PDFOptions.from_page_size("letter", margins=1.0, scale=0.8)
    cdp = opts.to_cdp()
    assert cdp["paperWidth"] == 8.5
    assert cdp["paperHeight"] == 11.0
    assert cdp["marginTop"] == 1.0
    assert cdp["scale"] == 0.8
    assert cdp["transferMode"] == "ReturnAsBase64"


def test_apply_expand_uniform():
    clip = ClipRect(x=50, y=100, width=200, height=150)
    exp = Expand.from_value(10)
    result = _apply_expand(clip, exp)
    assert result.x == 40
    assert result.y == 90
    assert result.width == 220
    assert result.height == 170


def test_apply_expand_clamps_to_zero():
    clip = ClipRect(x=3, y=5, width=100, height=100)
    exp = Expand.from_value(10)
    result = _apply_expand(clip, exp)
    assert result.x == 0
    assert result.y == 0
    assert result.width == 120  # 100 + left(10) + right(10)
    assert result.height == 120  # 100 + top(10) + bottom(10)
