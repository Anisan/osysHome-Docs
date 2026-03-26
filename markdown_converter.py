"""Markdown to HTML converter - cmarkgfm (GFM) preferred, markdown2 fallback."""

_markdown_converter = None
_markdown_converter_name = None


def get_markdown_converter():
    """Return (converter_func, name). Uses cmarkgfm for full GitHub Markdown support, falls back to markdown2."""
    global _markdown_converter, _markdown_converter_name
    if _markdown_converter is not None:
        return _markdown_converter, _markdown_converter_name

    try:
        import cmarkgfm
        from cmarkgfm.cmark import Options as CmarkOptions

        def _convert_cmarkgfm(text: str) -> str:
            opts = CmarkOptions.CMARK_OPT_UNSAFE | CmarkOptions.CMARK_OPT_FOOTNOTES
            return cmarkgfm.github_flavored_markdown_to_html(text, options=opts)
        _markdown_converter = _convert_cmarkgfm
        _markdown_converter_name = "cmarkgfm"
        return _markdown_converter, _markdown_converter_name
    except ImportError:
        pass

    try:
        import markdown2
        _markdown2_extras = [
            "fenced-code-blocks",
            "tables",
            "strike",
            "task_list",
            "break-on-newline",
            "cuddled-lists",
            "header-ids",
        ]
        def _convert_markdown2(text: str) -> str:
            return markdown2.markdown(text, extras=_markdown2_extras)
        _markdown_converter = _convert_markdown2
        _markdown_converter_name = "markdown2"
        return _markdown_converter, _markdown_converter_name
    except ImportError:
        pass

    raise ImportError("No Markdown converter available. Install cmarkgfm or markdown2: pip install cmarkgfm")
