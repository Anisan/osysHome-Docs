"""Markdown preprocessing and postprocessing - Jekyll links, Mermaid blocks, doc/asset URL resolution."""

import os
import re
from html import unescape
from typing import Optional, Callable
from urllib.parse import urlparse

from plugins.Docs.constants import DOC_ASSET_EXTENSIONS


def process_jekyll_links(text: str) -> str:
    """Process Jekyll syntax {% link docs/... %} inside markdown links.
    Replaces only ]({% link path %}) -> ](path) to avoid corrupting examples in backticks."""
    def replace_jekyll_link(match):
        jekyll_path = match.group(1)
        if jekyll_path.startswith("docs/"):
            jekyll_path = jekyll_path[5:]
        return f"]({jekyll_path})"
    # Match only inside link URL: ]({% link path %}) - not in inline code examples
    return re.sub(r'\]\(\{%\s*link\s+([^\s}]+)\s*%\}\)', replace_jekyll_link, text)


def process_mermaid_blocks(html: str) -> str:
    """Process mermaid code blocks and convert to div.mermaid.
    Handles: <pre><code class="language-mermaid">, <pre><code class="mermaid">,
    and cmarkgfm format <pre lang="mermaid"><code>."""
    def process_mermaid_block(match):
        content = match.group(1)
        content = unescape(content)
        content = content.strip()
        return f'<div class="mermaid">{content}</div>'

    patterns = [
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        r'<pre><code class="mermaid">(.*?)</code></pre>',
        r'<pre\s+lang="mermaid"><code>(.*?)</code></pre>',
    ]
    for pattern in patterns:
        html = re.sub(pattern, process_mermaid_block, html, flags=re.DOTALL)
    return html


# GitHub-style alert types: tag -> (css_class, title)
_ALERT_TYPES = {
    "[!NOTE]": ("docs-alert-note", "Note"),
    "[!TIP]": ("docs-alert-tip", "Tip"),
    "[!IMPORTANT]": ("docs-alert-important", "Important"),
    "[!WARNING]": ("docs-alert-warning", "Warning"),
    "[!CAUTION]": ("docs-alert-caution", "Caution"),
}

# Font Awesome icon classes for each alert type
_ALERT_ICONS = {
    "[!NOTE]": "fas fa-info-circle",
    "[!TIP]": "fas fa-lightbulb",
    "[!IMPORTANT]": "fas fa-bookmark",
    "[!WARNING]": "fas fa-exclamation-triangle",
    "[!CAUTION]": "fas fa-ban",
}


def process_github_alerts(html: str, translate: Optional[Callable[[str], str]] = None) -> str:
    """Convert blockquotes with [!NOTE], [!TIP], etc. to styled alert divs.
    translate: optional callback(title_key) -> translated string for alert titles."""
    tr = translate if callable(translate) else (lambda s: s)

    def replace_alert(match):
        full = match.group(0)
        content = match.group(1)
        for tag, (css_class, title_key) in _ALERT_TYPES.items():
            if tag in content:
                body = re.sub(re.escape(tag) + r"\s*", "", content, count=1)
                body = re.sub(r"<p>\s*</p>\s*", "", body)
                body = body.strip()
                icon_class = _ALERT_ICONS.get(tag, "fas fa-info-circle")
                icon_html = f'<i class="{icon_class}" aria-hidden="true"></i>'
                title = tr(title_key)
                header = f'<div class="docs-alert-title"><span class="docs-alert-icon">{icon_html}</span><span class="docs-alert-title-text">{title}</span></div>'
                return f'<div class="docs-alert {css_class}">{header}<div class="docs-alert-body">{body}</div></div>'
        return full

    return re.sub(
        r"<blockquote>\s*(.*?)\s*</blockquote>",
        replace_alert,
        html,
        flags=re.DOTALL,
    )


def process_color_swatches(html: str) -> str:
    """Add color swatches to inline code that contains HEX, RGB, or HSL color values."""

    def wrap_with_swatch(match):
        full = match.group(0)
        attrs = match.group(1) or ""
        content = match.group(2).strip()
        # Skip if code has language class (from fenced blocks)
        if 'class=' in attrs and 'language-' in attrs:
            return full
        # HEX: #RGB, #RRGGBB, #RRGGBBAA
        hex_m = re.match(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$', content)
        if hex_m:
            css_color = content
            return f'<span class="docs-color-inline"><span class="docs-color-swatch" style="background-color: {css_color}" aria-hidden="true"></span><code{attrs}>{content}</code></span>'
        # RGB/RGBA
        rgb_m = re.match(r'^rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)$', content)
        if rgb_m:
            r, g, b = int(rgb_m.group(1)), int(rgb_m.group(2)), int(rgb_m.group(3))
            if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                return f'<span class="docs-color-inline"><span class="docs-color-swatch" style="background-color: {content}" aria-hidden="true"></span><code{attrs}>{content}</code></span>'
        # HSL/HSLA
        hsl_m = re.match(r'^hsla?\s*\(\s*(\d+)\s*,\s*(\d+)%\s*,\s*(\d+)%(?:\s*,\s*[\d.]+)?\s*\)$', content)
        if hsl_m:
            return f'<span class="docs-color-inline"><span class="docs-color-swatch" style="background-color: {content}" aria-hidden="true"></span><code{attrs}>{content}</code></span>'
        return full

    # Match <code> or <code attr="..."> - content must be exactly a color
    return re.sub(
        r'<code(\s[^>]*)?>([^<]+)</code>',
        wrap_with_swatch,
        html,
    )


def process_code_blocks_for_prism(html: str) -> str:
    """Convert <pre lang="xxx"><code> (cmarkgfm format) to <pre><code class="language-xxx">
    so Prism.js can highlight. Runs after mermaid extraction."""
    def add_prism_class(match):
        lang = match.group(1)
        content = match.group(2)
        return f'<pre><code class="language-{lang}">{content}</code></pre>'
    return re.sub(
        r'<pre\s+lang="([^"]+)"><code>(.*?)</code></pre>',
        add_prism_class,
        html,
        flags=re.DOTALL,
    )


class LinkResolver:
    """Resolves doc and asset links, processes markdown/HTML for internal URLs."""

    def __init__(
        self,
        get_doc_entry: Callable[[str, str], Optional[dict]],
        url_for: Callable,
    ):
        self.get_doc_entry = get_doc_entry
        self.url_for = url_for

    def _resolve_source_relative_target(self, source_id: str, current_file_dir: str, relative_path: str) -> Optional[str]:
        """Resolve a relative path inside a docs source.

        Plugin docs are indexed relative to `plugins/<Name>/docs`, but assets and root README files
        may live one level above that directory. When a document is at the docs root, allow a single
        leading `../` to address the plugin root, matching GitHub-style paths used in plugin docs.
        """
        path = (relative_path or "").strip()
        if not path:
            return None
        base_dir = current_file_dir or ""
        if path.startswith("./"):
            path = path[2:]
        if path.startswith("../"):
            if base_dir:
                target = os.path.normpath(os.path.join(base_dir, path)).replace("\\", "/")
            elif source_id != "core":
                target = os.path.normpath(path[3:]).replace("\\", "/")
            else:
                target = os.path.normpath(path).replace("\\", "/")
        else:
            target = os.path.normpath(os.path.join(base_dir, path)).replace("\\", "/")
        if target.startswith("..") or "/.." in target:
            return None
        return target

    def resolve_doc_url(self, source_id: str, current_file_dir: str, link_url: str) -> Optional[str]:
        """Resolve relative .md link to URL if doc exists in index. Returns None if not found."""
        if not link_url.lower().endswith(".md"):
            return None
        parsed = urlparse(link_url)
        if parsed.scheme or link_url.startswith("#"):
            return None
        target = self._resolve_source_relative_target(source_id, current_file_dir, link_url)
        if not target:
            return None
        entry = self.get_doc_entry(source_id, target)
        if not entry and target.startswith("docs/"):
            entry = self.get_doc_entry(source_id, target[5:])
        if entry:
            return self.url_for("Docs.docs_home", category=source_id, file=entry["path"])
        return None

    def resolve_asset_url(self, source_id: str, current_file_dir: str, image_url: str) -> Optional[str]:
        """Resolve relative image/asset URL to docs asset route URL. Returns None for external/data URLs."""
        parsed = urlparse(image_url)
        if parsed.scheme or image_url.strip().startswith("#"):
            return None
        target = self._resolve_source_relative_target(source_id, current_file_dir, image_url)
        if not target:
            return None
        ext = os.path.splitext(target.split("?")[0])[1].lower()
        if ext not in DOC_ASSET_EXTENSIONS:
            return None
        return self.url_for("Docs.docs_asset_by_source", source_id=source_id, asset_path=target)

    def process_markdown_file_links(self, text: str, source_id: str, current_file_dir: str) -> str:
        """Process markdown links and file mentions; resolve to docs URLs."""
        def replace_markdown_link(match):
            link_text, link_url = match.group(1), match.group(2)
            new_url = self.resolve_doc_url(source_id, current_file_dir, link_url)
            if new_url:
                return f"[{link_text}]({new_url})"
            return match.group(0)
        text = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            lambda m: replace_markdown_link(m) if m.group(2).lower().endswith(".md") else m.group(0),
            text,
        )
        def replace_code_mention(match):
            file_mention = match.group(1)
            new_url = self.resolve_doc_url(source_id, current_file_dir, file_mention)
            if new_url:
                return f"[`{file_mention}`]({new_url})"
            return match.group(0)
        text = re.sub(r'`([^`]+\.md)`', replace_code_mention, text)
        def replace_plain(match):
            before, file_mention, after = match.group(1), match.group(2), match.group(3)
            if before and before.strip() and before.strip() in ["[", "`", "("]:
                return match.group(0)
            new_url = self.resolve_doc_url(source_id, current_file_dir, file_mention)
            if new_url:
                return f"{before}[{file_mention}]({new_url}){after}"
            return match.group(0)
        text = re.sub(
            r'(^|[\s\-:])([A-Za-z0-9_\-/]+\.md)([\s.,:;\)\]\n]|$)',
            replace_plain,
            text,
            flags=re.MULTILINE,
        )
        return text

    def process_markdown_links(self, html_content: str, source_id: str, current_file_dir: str) -> str:
        """Process HTML links in rendered markdown; resolve .md to docs URLs."""
        def replace_link_in_tag(match):
            before_href, link_url, after_href = match.group(1), match.group(2), match.group(3)
            new_url = self.resolve_doc_url(source_id, current_file_dir, link_url)
            if new_url:
                return f'<a{before_href}href="{new_url}"{after_href}>'
            return match.group(0)
        return re.sub(
            r'<a([^>]*?)\s+href=["\']([^"\']+)["\']([^>]*)>',
            replace_link_in_tag,
            html_content,
        )

    def process_markdown_images(self, html_content: str, source_id: str, current_file_dir: str) -> str:
        """Process <img src="..."> in HTML; resolve relative image URLs to docs asset route."""
        def replace_img_src(match):
            before, src, after = match.group(1), match.group(2), match.group(3)
            new_url = self.resolve_asset_url(source_id, current_file_dir, src)
            if new_url:
                # Ensure space before src to avoid <imgsrc="..."> when before is empty
                return f'<img{before} src="{new_url}"{after}>'
            return match.group(0)
        return re.sub(
            r'<img([^>]*?)\s+src=["\']([^"\']+)["\']([^>]*)>',
            replace_img_src,
            html_content,
        )
