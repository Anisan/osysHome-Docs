"""Constants for Docs plugin."""

import re

# Root-level .md files in plugin dirs to include (besides docs/ subdir)
PLUGIN_ROOT_DOC_NAMES = ("README.md", "README.ru.md", "GetStarted.md", "GetStarted.ru.md")

# Language suffix in filename: Name.XX.md -> language XX; Name.md -> default
DOC_LANG_RE = re.compile(r"^(.+)\.([a-z]{2})\.md$", re.IGNORECASE)

# Allowed image/asset extensions for doc-inlined resources
DOC_ASSET_EXTENSIONS = frozenset((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp"))
