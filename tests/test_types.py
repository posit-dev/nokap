from nokap._types import ClipRect, Expand, PDFOptions


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
