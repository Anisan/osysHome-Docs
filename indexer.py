"""Documentation index: scanning, Whoosh search, categories."""

from __future__ import annotations

import os
import re
import json
from datetime import datetime
from threading import Lock, Thread
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING

from plugins.Docs.constants import PLUGIN_ROOT_DOC_NAMES, DOC_LANG_RE

if TYPE_CHECKING:
    from plugins.Docs import Docs  # noqa: F401


def parse_doc_lang(path: str) -> Tuple[str, str]:
    """Parse path into (base_name, lang). E.g. README.ru.md -> ('README', 'ru'), README.md -> ('README', 'default')."""
    path = path.strip().replace("\\", "/")
    m = DOC_LANG_RE.match(path)
    if m:
        return m.group(1), m.group(2).lower()
    if path.lower().endswith(".md"):
        return path[:-3], "default"
    return path, "default"


def extract_title_and_excerpt(
    file_path: str, default_title: str, excerpt_len: int = 500
) -> Tuple[str, str]:
    """Read first lines; return (title, excerpt). Excerpt is plain text for search."""
    title = default_title
    excerpt = ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read(excerpt_len + 500)
        lines = content.split("\n")
        for line in lines[:10]:
            if line.startswith("# "):
                title = line[2:].strip()
                break
            if line.startswith("## "):
                title = line[3:].strip()
                break
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", content)
        plain = re.sub(r"#+\s*", "", plain)
        plain = re.sub(r"[*_`]", "", plain)
        excerpt = " ".join(plain.split())[:excerpt_len]
    except Exception:
        pass
    return title, excerpt


def filter_index_by_locale(entries: List[Dict[str, Any]], locale: str) -> List[Dict[str, Any]]:
    """Return one entry per (source_id, base_name): prefer locale, else default."""
    locale = (locale or "en").lower()[:2]

    def score(entry: Dict[str, Any]) -> int:
        lang = (entry.get("lang") or "default").lower()
        if lang == locale:
            return 2
        if lang == "default":
            return 1
        return 0

    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in entries:
        key = (e["source_id"], e["base_name"])
        if key not in by_key or score(e) > score(by_key[key]):
            by_key[key] = e
    return list(by_key.values())


def get_doc_entry(docs_index: List[Dict], source_id: str, path: str) -> Optional[Dict[str, Any]]:
    """Return index entry for (source_id, path) or None."""
    path_norm = os.path.normpath(path).replace("\\", "/")
    for entry in docs_index:
        if entry["source_id"] == source_id and entry["path"].replace("\\", "/") == path_norm:
            return entry
    return None


def build_docs_index(plugin: "Docs") -> None:
    """Scan all doc sources and fill plugin._docs_index. Clears HTML cache."""
    plugin._set_index_progress(
        status="running", phase="scan", processed=0, total=None, message="Scanning documentation..."
    )
    plugin._html_cache.clear()
    plugin._category_docs_cache.clear()
    index: List[Dict[str, Any]] = []
    scanned = 0

    core_docs = os.path.join(plugin.project_root, "docs")
    if os.path.isdir(core_docs):
        for root, _dirs, files in os.walk(core_docs):
            for name in files:
                if not name.lower().endswith(".md"):
                    continue
                full = os.path.join(root, name)
                if not os.path.isfile(full):
                    continue
                rel = os.path.relpath(full, core_docs).replace("\\", "/")
                base_name, lang = parse_doc_lang(rel)
                default_title = base_name.replace("_", " ")
                title, excerpt = extract_title_and_excerpt(full, default_title)
                index.append({
                    "source_id": "core",
                    "path": rel,
                    "base_name": base_name,
                    "lang": lang,
                    "title": title,
                    "file_path": full,
                    "excerpt": excerpt,
                })
                scanned += 1
                if scanned % 25 == 0:
                    plugin._set_index_progress(
                        status="running", phase="scan", processed=scanned, total=None,
                        message=f"Scanning... {scanned} docs",
                    )

    for plugin_name in plugin._discover_plugin_names():
        plugin_path = os.path.join(plugin.plugins_dir, plugin_name)
        plugin_docs = os.path.join(plugin_path, "docs")
        if os.path.isdir(plugin_docs):
            for root, _dirs, files in os.walk(plugin_docs):
                for name in files:
                    if not name.lower().endswith(".md"):
                        continue
                    full = os.path.join(root, name)
                    if not os.path.isfile(full):
                        continue
                    rel = os.path.relpath(full, plugin_docs).replace("\\", "/")
                    base_name, lang = parse_doc_lang(rel)
                    default_title = base_name.replace("_", " ")
                    title, excerpt = extract_title_and_excerpt(full, default_title)
                    index.append({
                        "source_id": plugin_name,
                        "path": rel,
                        "base_name": base_name,
                        "lang": lang,
                        "title": title,
                        "file_path": full,
                        "excerpt": excerpt,
                    })
                    scanned += 1
                    if scanned % 25 == 0:
                        plugin._set_index_progress(
                            status="running", phase="scan", processed=scanned, total=None,
                            message=f"Scanning... {scanned} docs",
                        )
        for doc_name in PLUGIN_ROOT_DOC_NAMES:
            full = os.path.join(plugin_path, doc_name)
            if os.path.isfile(full):
                base_name, lang = parse_doc_lang(doc_name)
                default_title = base_name.replace("_", " ")
                title, excerpt = extract_title_and_excerpt(full, default_title)
                index.append({
                    "source_id": plugin_name,
                    "path": doc_name,
                    "base_name": base_name,
                    "lang": lang,
                    "title": title,
                    "file_path": full,
                    "excerpt": excerpt,
                })
                scanned += 1
                if scanned % 25 == 0:
                    plugin._set_index_progress(
                        status="running", phase="scan", processed=scanned, total=None,
                        message=f"Scanning... {scanned} docs",
                    )

    plugin._docs_index = index
    plugin._doc_entry_map = {
        (entry["source_id"], entry["path"].replace("\\", "/")): entry
        for entry in plugin._docs_index
    }
    docs_by_source: Dict[str, List[Dict[str, Any]]] = {}
    for entry in plugin._docs_index:
        docs_by_source.setdefault(entry["source_id"], []).append(entry)
    plugin._docs_by_source = docs_by_source
    plugin._set_index_progress(
        status="running", phase="whoosh", processed=0, total=len(plugin._docs_index),
        message="Building search index (Whoosh)...",
    )
    build_whoosh_index(plugin)
    plugin._index_built_at = datetime.now()
    plugin._set_index_progress(
        status="done", phase="done", processed=len(plugin._docs_index),
        total=len(plugin._docs_index), message="Index ready.",
    )
    plugin.logger.info("Docs index built: %s entries", len(plugin._docs_index))


def build_whoosh_index(plugin: "Docs") -> None:
    """Build Whoosh full-text search index from _docs_index."""
    from app.core.lib.cache import clearCache
    try:
        from whoosh.analysis import LanguageAnalyzer
        from whoosh.fields import Schema, TEXT, ID
        from whoosh.index import create_in, exists_in
    except ImportError:
        plugin.logger.debug("Whoosh not installed, full-text search disabled")
        return
    try:
        schema = Schema(
            path=ID(stored=True),
            source_id=ID(stored=True),
            base_name=ID(stored=True),
            lang=ID(stored=True),
            title=TEXT(stored=True),
            title_ru=TEXT(stored=True, analyzer=LanguageAnalyzer("ru")),
            content_ru=TEXT(stored=True, analyzer=LanguageAnalyzer("ru")),
            title_en=TEXT(stored=True, analyzer=LanguageAnalyzer("en")),
            content_en=TEXT(stored=True, analyzer=LanguageAnalyzer("en")),
        )
        os.makedirs(plugin._whoosh_index_dir, exist_ok=True)
        if exists_in(plugin._whoosh_index_dir):
            clearCache("Docs/whoosh")
            os.makedirs(plugin._whoosh_index_dir, exist_ok=True)
        ix = create_in(plugin._whoosh_index_dir, schema)
        writer = ix.writer()
        total = len(plugin._docs_index)
        done = 0
        for entry in plugin._docs_index:
            file_path = entry.get("file_path")
            if not file_path or not os.path.isfile(file_path):
                done += 1
                continue
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                lang = (entry.get("lang") or "default").lower()
                is_ru = lang in ("ru", "uk", "be")
                is_en = lang in ("en",)
                writer.add_document(
                    path=entry["path"],
                    source_id=entry["source_id"],
                    base_name=entry["base_name"],
                    lang=lang,
                    title=entry.get("title", ""),
                    title_ru=entry.get("title", "") if is_ru or lang == "default" else "",
                    content_ru=content if is_ru or lang == "default" else "",
                    title_en=entry.get("title", "") if is_en or lang == "default" else "",
                    content_en=content if is_en or lang == "default" else "",
                )
            except Exception as ex:
                plugin.logger.debug("Whoosh: skip %s: %s", file_path, ex)
            finally:
                done += 1
                if done % 10 == 0 or done == total:
                    plugin._set_index_progress(
                        status="running", phase="whoosh", processed=done, total=total,
                        message=f"Building Whoosh index... {done}/{total}",
                    )
        writer.commit()
        plugin.logger.debug("Whoosh index built in %s", plugin._whoosh_index_dir)
    except Exception as ex:
        plugin.logger.warning("Whoosh index build failed: %s", ex)


def search_docs_whoosh(plugin: "Docs", q: str) -> List[Dict[str, Any]]:
    """Search via Whoosh; return list of entries for filter_index_by_locale."""
    if not q or not q.strip():
        return []
    try:
        from whoosh.index import exists_in, open_dir
        from whoosh.qparser import MultifieldParser, OrGroup
    except ImportError:
        return []
    try:
        if not exists_in(plugin._whoosh_index_dir):
            return []
        ix = open_dir(plugin._whoosh_index_dir)
        parser = MultifieldParser(
            ["title_ru", "content_ru", "title_en", "content_en"],
            schema=ix.schema,
            group=OrGroup,
        )
        qparsed = parser.parse(q)
        with ix.searcher() as searcher:
            results = searcher.search(qparsed, limit=100)
            out = []
            for hit in results:
                snippet = None
                try:
                    snippet = (
                        hit.highlights("content_ru", top=2, minscore=1)
                        or hit.highlights("content_en", top=2, minscore=1)
                    )
                    if snippet:
                        snippet = snippet.strip()
                except Exception:
                    snippet = None
                out.append({
                    "source_id": hit["source_id"],
                    "path": hit["path"],
                    "base_name": hit["base_name"],
                    "lang": hit.get("lang", "default"),
                    "title": hit.get("title", "") or hit.get("title_ru", "") or hit.get("title_en", ""),
                    "snippet": snippet,
                })
            return out
    except Exception as ex:
        plugin.logger.debug("Whoosh search failed: %s", ex)
        return []


def search_docs(
    plugin: "Docs", q: str, locale: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search via Whoosh or fallback to substring. Locale filter applied."""
    from flask import url_for
    matches = search_docs_whoosh(plugin, q)
    if not matches and q:
        q_lower = q.lower()
        matches = [
            e for e in plugin._docs_index
            if q_lower in (e.get("title") or "").lower() or q_lower in (e.get("excerpt") or "").lower()
        ]
    if locale:
        matches = filter_index_by_locale(matches, locale)
    return [
        {
            "title": e["title"],
            "url": url_for("Docs.docs_home", category=e["source_id"], file=e["path"]),
            "source_id": e["source_id"],
            "path": e["path"],
            "snippet": e.get("snippet") or e.get("excerpt") or "",
        }
        for e in matches
    ]


def get_index_info(plugin: "Docs") -> Dict[str, Any]:
    """Return diagnostic info for admin page."""
    whoosh_installed = False
    whoosh_ready = False
    whoosh_error = None
    whoosh_files = 0
    whoosh_bytes = 0
    try:
        from whoosh.index import exists_in  # type: ignore
        whoosh_installed = True
        whoosh_ready = os.path.isdir(plugin._whoosh_index_dir) and exists_in(plugin._whoosh_index_dir)
        if os.path.isdir(plugin._whoosh_index_dir):
            for root, _dirs, files in os.walk(plugin._whoosh_index_dir):
                for fn in files:
                    whoosh_files += 1
                    try:
                        whoosh_bytes += os.path.getsize(os.path.join(root, fn))
                    except OSError:
                        pass
    except Exception as ex:
        whoosh_error = str(ex)

    built_at = plugin._index_built_at.isoformat(sep=" ", timespec="seconds") if plugin._index_built_at else None
    docs_by_source: Dict[str, int] = {}
    for e in plugin._docs_index:
        sid = e.get("source_id") or "unknown"
        docs_by_source[sid] = docs_by_source.get(sid, 0) + 1

    return {
        "docs_count": len(plugin._docs_index),
        "docs_by_source": docs_by_source,
        "built_at": built_at,
        "whoosh": {
            "installed": whoosh_installed,
            "ready": whoosh_ready,
            "dir": plugin._whoosh_index_dir,
            "files": whoosh_files,
            "bytes": whoosh_bytes,
            "error": whoosh_error,
        },
    }


def get_home_categories(plugin: "Docs") -> List[Dict[str, Any]]:
    """Return list of categories for sidebar."""
    from flask import current_app
    by_source: Dict[str, bool] = {e["source_id"]: True for e in plugin._docs_index}
    assets = (current_app.config.get("ASSETS_ROOT") or "").rstrip("/")
    system_icon = f"{assets}/images/logo.png" if assets else "/images/logo.png"
    categories = []
    if "core" in by_source:
        categories.append({"source_id": "core", "heading": "OsysHome", "icon_url": system_icon})
    for sid in sorted(by_source.keys(), key=lambda s: s.lower()):
        if sid == "core":
            continue
        categories.append({"source_id": sid, "heading": sid, "icon_url": f"/{sid}/static/{sid}.png"})
    return categories


def get_documents_for_category(
    plugin: "Docs", source_id: str, locale: str
) -> List[Dict[str, Any]]:
    """Return docs for one category, filtered by locale."""
    from flask import url_for
    locale_key = (locale or "en").lower()[:2]
    cache_key = (source_id, locale_key)
    cached = plugin._category_docs_cache.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    entries = plugin._docs_by_source.get(source_id, [])
    filtered = filter_index_by_locale(entries, locale)
    out = []
    for e in filtered:
        out.append({
            "title": e["title"],
            "path": e["path"],
            "excerpt": (e.get("excerpt") or "").strip()[:300],
            "home_url": url_for("Docs.docs_home", category=e["source_id"], file=e["path"]),
        })
    out.sort(key=lambda x: x["title"].lower())
    plugin._category_docs_cache[cache_key] = [dict(item) for item in out]
    return out


def build_home_sections(plugin: "Docs", locale: str) -> List[Dict[str, Any]]:
    """Build sections for home (legacy)."""
    sections = []
    for cat in get_home_categories(plugin):
        docs = get_documents_for_category(plugin, cat["source_id"], locale)
        if docs:
            sections.append({
                "heading": cat["heading"],
                "source_id": cat["source_id"],
                "documents": docs,
            })
    return sections
