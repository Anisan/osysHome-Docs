"""Docs plugin - provides access to project documentation"""

import os
import re
import json
from datetime import datetime
from html import unescape
from threading import Lock, Thread
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from flask import abort, current_app, jsonify, redirect, render_template, request, send_from_directory, url_for
from app.core.main.BasePlugin import BasePlugin
from app.core.lib.cache import clearCache, existInCache, findInCache, getCacheDir, getFullFilename, saveToCache
from app.authentication.handlers import handle_user_required


# Root-level .md files in plugin dirs to include (besides docs/ subdir)
PLUGIN_ROOT_DOC_NAMES = ("README.md", "README.ru.md", "GetStarted.md", "GetStarted.ru.md")

# Language suffix in filename: Name.XX.md -> language XX; Name.md -> default
DOC_LANG_RE = re.compile(r"^(.+)\.([a-z]{2})\.md$", re.IGNORECASE)

# Allowed image/asset extensions for doc-inlined resources
DOC_ASSET_EXTENSIONS = frozenset((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp"))


class Docs(BasePlugin):
    """Plugin for viewing project documentation"""

    def __init__(self, app):
        super().__init__(app, "Docs")
        self.title = "Documentation"
        self.description = "Project documentation viewer"
        self.category = "System"
        self.author = "osysHome"
        self.version = 1
        self.actions = []

        # Path to docs directory within this plugin (so docs can be updated by plugin only).
        # Use __file__ so it works regardless of how PLUGINS_FOLDER is configured.
        self.docs_dir = os.path.join(os.path.dirname(__file__), "docs")

        # Project root and dev-docs output directory (pdoc).
        # NOTE: Config.PROJECT_ROOT in core currently points one level ABOVE the repo root,
        # so we compute the repo root from this plugin file instead:
        #   <repo>/plugins/Docs/__init__.py -> <repo>
        self.project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
        )
        self.docs_dev_dir = os.path.join(self.project_root, "docs_dev")
        self.plugins_dir = os.path.join(self.project_root, "plugins")

        # In-memory index: list of {"source_id", "path", "title", "file_path", "excerpt"}
        self._docs_index: List[Dict[str, Any]] = []
        # HTML cache: key (source_id, path) -> rendered HTML (invalidated on index rebuild)
        self._html_cache: Dict[Tuple[str, str], str] = {}
        # Whoosh full-text search index (stored in app cache)
        self._whoosh_index_dir = os.path.join(getCacheDir(), "Docs", "whoosh")
        self._index_built_at: Optional[datetime] = None
        self._index_build_lock = Lock()
        self._index_build_thread: Optional[Thread] = None
        self._progress_filename = "index_progress.json"

    def initialization(self):
        """Called when plugin starts. Index is built lazily on first docs access to avoid delaying startup."""
        self.logger.info("Docs plugin initialized")
    
    def admin(self, request):
        """Admin page - shows documentation index"""
        status_message = None
        status_ok = None

        # Handle actions from admin UI
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "generate_pdoc":
                try:
                    from plugins.Docs.pdoc_generator import generate_docs_dev

                    ok, msg = generate_docs_dev(project_root=self.project_root)
                    status_ok = ok
                    status_message = msg
                except Exception as ex:
                    status_ok = False
                    status_message = str(ex)
            elif action == "refresh_index":
                try:
                    started = self._start_index_rebuild_async()
                    status_ok = True
                    status_message = "Index rebuild started." if started else "Index rebuild already running."
                except Exception as ex:
                    status_ok = False
                    status_message = str(ex)

        if not self._docs_index:
            self._build_docs_index()

        docs_dev_index = os.path.join(self.docs_dev_dir, "index.html")
        has_docs_dev = os.path.isfile(docs_dev_index)

        context = {
            "title": self.title,
            "has_docs_dev": has_docs_dev,
            "status_ok": status_ok,
            "status_message": status_message,
            "index_info": self._get_index_info(),
            "index_progress": self._get_index_progress(),
        }
        return self.render("docs_admin.html", context)

    def route_docs(self):
        """Public docs routes: home (from index), list, view by source, backward compat."""

        @self.blueprint.route("/docs")
        @self.blueprint.route("/docs/")
        @handle_user_required
        def docs_home():
            if not self._docs_index:
                self._build_docs_index()
            try:
                from app import get_current_language
                locale = get_current_language() or "en"
            except Exception:
                locale = "en"
            categories = self._get_home_categories()
            selected_id = request.args.get("category", "").strip() or (categories[0]["source_id"] if categories else "")
            if selected_id and not any(c["source_id"] == selected_id for c in categories):
                selected_id = categories[0]["source_id"] if categories else ""
            selected_file = request.args.get("file", "").strip()
            tree = []
            for cat in categories:
                docs = self._get_documents_for_category(cat["source_id"], locale)
                for d in docs:
                    d["home_url"] = url_for("Docs.docs_home", category=cat["source_id"], file=d["path"])
                tree.append({
                    "source_id": cat["source_id"],
                    "heading": cat["heading"],
                    "icon_url": cat["icon_url"],
                    "documents": docs,
                })
            doc_content_html = None
            doc_title = None
            if selected_id and selected_file:
                content_result = self._get_doc_content_html(selected_id, selected_file)
                if content_result:
                    doc_content_html, doc_title = content_result
            selected_heading = next((c["heading"] for c in categories if c["source_id"] == selected_id), selected_id)
            category_documents = next((t["documents"] for t in tree if t["source_id"] == selected_id), [])
            return render_template(
                "docs/home.html",
                tree=tree,
                selected_category=selected_id,
                selected_file=selected_file,
                selected_heading=selected_heading,
                category_documents=category_documents,
                doc_content_html=doc_content_html,
                doc_title=doc_title,
                locale=locale,
            )

        @self.blueprint.route("/docs/<source_id>/asset/<path:asset_path>")
        @handle_user_required
        def docs_asset_by_source(source_id, asset_path):
            return self._serve_doc_asset(source_id, asset_path)

        @self.blueprint.route("/docs/<source_id>/<path:doc_path>")
        @handle_user_required
        def docs_view_by_source(source_id, doc_path):
            # Render clean document view without sidebar
            return self._render_markdown_doc_by_source(source_id, doc_path)

        @self.blueprint.route("/docs/search")
        @handle_user_required
        def docs_search():
            q = (request.args.get("q") or "").strip()
            if not self._docs_index:
                self._build_docs_index()
            try:
                from app import get_current_language
                locale = get_current_language() or "en"
            except Exception:
                locale = "en"
            results = self._search_docs(q, locale) if q else []
            if request.args.get("format") == "json":
                return jsonify({
                    "query": q,
                    "results": [
                        {"title": r["title"], "url": r["url"], "source_id": r["source_id"], "path": r["path"]}
                        for r in results
                    ],
                })
            categories = self._get_home_categories()
            tree = []
            for cat in categories:
                docs = self._get_documents_for_category(cat["source_id"], locale)
                for d in docs:
                    d["home_url"] = url_for("Docs.docs_home", category=cat["source_id"], file=d["path"])
                tree.append({
                    "source_id": cat["source_id"],
                    "heading": cat["heading"],
                    "icon_url": cat["icon_url"],
                    "documents": docs,
                })
            return render_template(
                "docs/search.html",
                tree=tree,
                query=q,
                results=results,
                locale=locale,
            )

        @self.blueprint.route("/docs/index_status")
        @handle_user_required
        def docs_index_status():
            # Used by admin UI polling
            return jsonify({
                "index_info": self._get_index_info(),
                "index_progress": self._get_index_progress(),
            })

        @self.blueprint.route("/docs/<path:filename>")
        @handle_user_required
        def docs_view_legacy(filename):
            # Backward compatibility: /docs/<name>.md -> /docs/Docs/<name>.md
            safe = os.path.normpath(filename)
            if safe.startswith("..") or safe.startswith("/"):
                abort(404)
            if safe.lower().endswith(".md"):
                return redirect(url_for("Docs.docs_home", category="Docs", file=safe))
            abort(404)

    def route_docs_dev(self):
        """Developer docs (pdoc) routes (moved from core admin/routes.py)."""

        @self.blueprint.route("/docs_dev")
        @self.blueprint.route("/docs_dev/")
        @self.blueprint.route("/docs_dev/<path:filename>")
        @handle_user_required
        def docs_dev(filename=None):
            if filename is None:
                safe_path = "index.html"
            else:
                safe_path = os.path.normpath(filename)
                if safe_path.startswith("..") or safe_path.startswith("/"):
                    abort(404)
                if not safe_path or safe_path == ".":
                    safe_path = "index.html"

            full_path = os.path.join(self.docs_dev_dir, safe_path)

            if not os.path.isfile(full_path):
                if not safe_path.endswith("index.html"):
                    index_path = os.path.join(os.path.dirname(full_path), "index.html")
                    if os.path.isfile(index_path):
                        full_path = index_path
                    else:
                        abort(404)
                else:
                    abort(404)

            if safe_path.endswith(".html"):
                mimetype = "text/html"
            elif safe_path.endswith(".css"):
                mimetype = "text/css"
            elif safe_path.endswith(".js"):
                mimetype = "application/javascript"
            else:
                mimetype = None

            return send_from_directory(
                self.docs_dev_dir,
                os.path.relpath(full_path, self.docs_dev_dir).replace("\\", "/"),
                mimetype=mimetype,
            )

    def _discover_plugin_names(self) -> List[str]:
        """List names of enabled (active) plugins only. Disabled modules are not scanned."""
        try:
            from app.core.main.PluginsHelper import plugins
            names = list(plugins.keys())
        except Exception:
            names = []
        names.sort(key=lambda s: s.lower())
        return names

    @staticmethod
    def _parse_doc_lang(path: str) -> Tuple[str, str]:
        """Parse path into (base_name, lang). E.g. README.ru.md -> ('README', 'ru'), README.md -> ('README', 'default')."""
        path = path.strip().replace("\\", "/")
        m = DOC_LANG_RE.match(path)
        if m:
            return m.group(1), m.group(2).lower()
        if path.lower().endswith(".md"):
            return path[:-3], "default"
        return path, "default"

    @staticmethod
    def _extract_title_and_excerpt(file_path: str, default_title: str, excerpt_len: int = 500) -> Tuple[str, str]:
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
            # Excerpt: strip markdown, take first chars
            plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", content)
            plain = re.sub(r"#+\s*", "", plain)
            plain = re.sub(r"[*_`]", "", plain)
            excerpt = " ".join(plain.split())[:excerpt_len]
        except Exception:
            pass
        return title, excerpt

    def _build_docs_index(self) -> None:
        """Scan all doc sources and fill self._docs_index. Clears HTML cache."""
        self._set_index_progress(status="running", phase="scan", processed=0, total=None, message="Scanning documentation...")
        self._html_cache.clear()
        index: List[Dict[str, Any]] = []
        scanned = 0

        # 1) Core: project_root/docs/
        core_docs = os.path.join(self.project_root, "docs")
        if os.path.isdir(core_docs):
            for root, _dirs, files in os.walk(core_docs):
                for name in files:
                    if not name.lower().endswith(".md"):
                        continue
                    full = os.path.join(root, name)
                    if not os.path.isfile(full):
                        continue
                    rel = os.path.relpath(full, core_docs).replace("\\", "/")
                    base_name, lang = self._parse_doc_lang(rel)
                    default_title = base_name.replace("_", " ")
                    title, excerpt = self._extract_title_and_excerpt(full, default_title)
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
                        self._set_index_progress(status="running", phase="scan", processed=scanned, total=None, message=f"Scanning... {scanned} docs")

        # 2) Plugins (including Docs): plugins/<name>/docs/ and plugins/<name>/{README,GetStarted}.md
        for plugin_name in self._discover_plugin_names():
            plugin_path = os.path.join(self.plugins_dir, plugin_name)
            # docs/ subdir
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
                        base_name, lang = self._parse_doc_lang(rel)
                        default_title = base_name.replace("_", " ")
                        title, excerpt = self._extract_title_and_excerpt(full, default_title)
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
                            self._set_index_progress(status="running", phase="scan", processed=scanned, total=None, message=f"Scanning... {scanned} docs")
            # Root-level known .md files
            for doc_name in PLUGIN_ROOT_DOC_NAMES:
                full = os.path.join(plugin_path, doc_name)
                if os.path.isfile(full):
                    base_name, lang = self._parse_doc_lang(doc_name)
                    default_title = base_name.replace("_", " ")
                    title, excerpt = self._extract_title_and_excerpt(full, default_title)
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
                        self._set_index_progress(status="running", phase="scan", processed=scanned, total=None, message=f"Scanning... {scanned} docs")

        self._docs_index = index
        self._set_index_progress(status="running", phase="whoosh", processed=0, total=len(self._docs_index), message="Building search index (Whoosh)...")
        self._build_whoosh_index()
        self._index_built_at = datetime.now()
        self._set_index_progress(status="done", phase="done", processed=len(self._docs_index), total=len(self._docs_index), message="Index ready.")
        self.logger.info("Docs index built: %s entries", len(self._docs_index))

    def _start_index_rebuild_async(self) -> bool:
        """Start index rebuild in a background thread. Returns True if started."""
        with self._index_build_lock:
            if self._index_build_thread and self._index_build_thread.is_alive():
                return False

            def run():
                try:
                    self._build_docs_index()
                except Exception as ex:
                    self.logger.exception(ex)
                    self._set_index_progress(status="error", phase="error", processed=None, total=None, message=str(ex))

            t = Thread(target=run, name="DocsIndexRebuild", daemon=True)
            self._index_build_thread = t
            t.start()
            return True

    def _get_index_progress(self) -> Dict[str, Any]:
        """Read current progress from cache."""
        try:
            if not existInCache(self._progress_filename, directory="Docs"):
                return {"status": "idle"}
            fp = getFullFilename(self._progress_filename, directory="Docs")
            with open(fp, "rb") as f:
                return json.loads(f.read().decode("utf-8"))
        except Exception:
            return {"status": "unknown"}

    def _set_index_progress(
        self,
        *,
        status: str,
        phase: str,
        processed: Optional[int],
        total: Optional[int],
        message: str,
    ) -> None:
        payload = {
            "status": status,
            "phase": phase,
            "processed": processed,
            "total": total,
            "message": message,
            "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        }
        try:
            saveToCache(self._progress_filename, json.dumps(payload).encode("utf-8"), directory="Docs")
        except Exception:
            pass

    def _get_index_info(self) -> Dict[str, Any]:
        """Return diagnostic info for admin page."""
        whoosh_installed = False
        whoosh_ready = False
        whoosh_error = None
        whoosh_files = 0
        whoosh_bytes = 0
        try:
            from whoosh.index import exists_in  # type: ignore

            whoosh_installed = True
            whoosh_ready = os.path.isdir(self._whoosh_index_dir) and exists_in(self._whoosh_index_dir)
            if os.path.isdir(self._whoosh_index_dir):
                for root, _dirs, files in os.walk(self._whoosh_index_dir):
                    for fn in files:
                        whoosh_files += 1
                        try:
                            whoosh_bytes += os.path.getsize(os.path.join(root, fn))
                        except OSError:
                            pass
        except Exception as ex:
            # ImportError or Whoosh internal errors should not break admin page
            whoosh_error = str(ex)

        built_at = self._index_built_at.isoformat(sep=" ", timespec="seconds") if self._index_built_at else None
        docs_by_source: Dict[str, int] = {}
        for e in self._docs_index:
            sid = e.get("source_id") or "unknown"
            docs_by_source[sid] = docs_by_source.get(sid, 0) + 1

        return {
            "docs_count": len(self._docs_index),
            "docs_by_source": docs_by_source,
            "built_at": built_at,
            "whoosh": {
                "installed": whoosh_installed,
                "ready": whoosh_ready,
                "dir": self._whoosh_index_dir,
                "files": whoosh_files,
                "bytes": whoosh_bytes,
                "error": whoosh_error,
            },
        }

    def _build_whoosh_index(self) -> None:
        """Build Whoosh full-text search index from _docs_index (full file content)."""
        try:
            from whoosh.analysis import LanguageAnalyzer
            from whoosh.fields import Schema, TEXT, ID
            from whoosh.index import create_in, exists_in
        except ImportError:
            self.logger.debug("Whoosh not installed, full-text search disabled")
            return
        try:
            schema = Schema(
                path=ID(stored=True),
                source_id=ID(stored=True),
                base_name=ID(stored=True),
                lang=ID(stored=True),
                title=TEXT(stored=True),
                # Full-text fields with language analyzers (Russian morphology support)
                title_ru=TEXT(stored=True, analyzer=LanguageAnalyzer("ru")),
                content_ru=TEXT(stored=True, analyzer=LanguageAnalyzer("ru")),
                title_en=TEXT(stored=True, analyzer=LanguageAnalyzer("en")),
                content_en=TEXT(stored=True, analyzer=LanguageAnalyzer("en")),
            )
            os.makedirs(self._whoosh_index_dir, exist_ok=True)
            if exists_in(self._whoosh_index_dir):
                clearCache("Docs/whoosh")
                os.makedirs(self._whoosh_index_dir, exist_ok=True)
            ix = create_in(self._whoosh_index_dir, schema)
            writer = ix.writer()
            total = len(self._docs_index)
            done = 0
            for entry in self._docs_index:
                file_path = entry.get("file_path")
                if not file_path or not os.path.isfile(file_path):
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    lang = (entry.get("lang") or "default").lower()
                    is_ru = lang in ("ru", "uk", "be")  # treat close Cyrillic locales as ru analyzer
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
                    self.logger.debug("Whoosh: skip %s: %s", file_path, ex)
                finally:
                    done += 1
                    if done % 10 == 0 or done == total:
                        self._set_index_progress(
                            status="running",
                            phase="whoosh",
                            processed=done,
                            total=total,
                            message=f"Building Whoosh index... {done}/{total}",
                        )
            writer.commit()
            self.logger.debug("Whoosh index built in %s", self._whoosh_index_dir)
        except Exception as ex:
            self.logger.warning("Whoosh index build failed: %s", ex)

    def _search_docs_whoosh(self, q: str) -> List[Dict[str, Any]]:
        """Search via Whoosh; return list of entries for _filter_index_by_locale."""
        if not q or not q.strip():
            return []
        try:
            from whoosh.index import exists_in, open_dir
            from whoosh.qparser import MultifieldParser, OrGroup
        except ImportError:
            return []
        try:
            if not exists_in(self._whoosh_index_dir):
                return []
            ix = open_dir(self._whoosh_index_dir)
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
                        snippet = hit.highlights("content_ru", top=2, minscore=1) or hit.highlights("content_en", top=2, minscore=1)
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
            self.logger.debug("Whoosh search failed: %s", ex)
            return []

    def _filter_index_by_locale(self, entries: List[Dict[str, Any]], locale: str) -> List[Dict[str, Any]]:
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

    def _get_doc_entry(self, source_id: str, path: str) -> Optional[Dict[str, Any]]:
        """Return index entry for (source_id, path) or None."""
        path_norm = os.path.normpath(path).replace("\\", "/")
        for entry in self._docs_index:
            if entry["source_id"] == source_id and entry["path"].replace("\\", "/") == path_norm:
                return entry
        return None

    def _search_docs(self, q: str, locale: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search via Whoosh (full-text) or fallback to substring in title/excerpt. Locale filter applied."""
        matches = self._search_docs_whoosh(q)
        if not matches and q:
            q_lower = q.lower()
            matches = [
                e for e in self._docs_index
                if q_lower in (e.get("title") or "").lower() or q_lower in (e.get("excerpt") or "").lower()
            ]
        if locale:
            matches = self._filter_index_by_locale(matches, locale)
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

    def _get_home_categories(self) -> List[Dict[str, Any]]:
        """Return list of categories for sidebar: [{"source_id", "heading", "icon_url"}, ...] in order.
        Icon convention: each module has its icon in static/<ModuleName>.png; URL is /<ModuleName>/static/<ModuleName>.png."""
        by_source: Dict[str, bool] = {e["source_id"]: True for e in self._docs_index}
        assets = (current_app.config.get("ASSETS_ROOT") or "").rstrip("/")
        system_icon = f"{assets}/images/logo.png" if assets else "/images/logo.png"
        categories = []
        if "core" in by_source:
            categories.append({"source_id": "core", "heading": "OsysHome", "icon_url": system_icon})
        for sid in sorted(by_source.keys(), key=lambda s: s.lower()):
            if sid == "core":
                continue
            # Plugin icon: plugins/<sid>/static/<sid>.png -> URL /<sid>/static/<sid>.png (same as sidebar).
            # Docs plugin ("Docs") следует тем же правилам, что и остальные плагины.
            categories.append({"source_id": sid, "heading": sid, "icon_url": f"/{sid}/static/{sid}.png"})
        return categories

    def _get_documents_for_category(self, source_id: str, locale: str) -> List[Dict[str, Any]]:
        """Return docs for one category, filtered by locale (one per base_name), with excerpt."""
        entries = [e for e in self._docs_index if e["source_id"] == source_id]
        filtered = self._filter_index_by_locale(entries, locale)
        out = []
        for e in filtered:
            out.append({
                "title": e["title"],
                "path": e["path"],
                "excerpt": (e.get("excerpt") or "").strip()[:300],
                "url": url_for("Docs.docs_home", category=e["source_id"], file=e["path"]),
            })
        out.sort(key=lambda x: x["title"].lower())
        return out

    def _build_home_sections(self, locale: str) -> List[Dict[str, Any]]:
        """Build sections for home (legacy): Core, Docs, plugins with documents filtered by locale."""
        sections = []
        for cat in self._get_home_categories():
            docs = self._get_documents_for_category(cat["source_id"], locale)
            if docs:
                sections.append({"heading": cat["heading"], "source_id": cat["source_id"], "documents": docs})
        return sections

    def _get_source_base_dir(self, source_id: str) -> Optional[str]:
        """Return filesystem path to the root of doc source, or None."""
        if source_id == "core":
            return os.path.join(self.project_root, "docs")
        if source_id == "Docs":
            return self.docs_dir
        plugin_path = os.path.join(self.plugins_dir, source_id)
        if os.path.isdir(plugin_path):
            return plugin_path
        return None

    def _serve_doc_asset(self, source_id: str, asset_path: str):
        """Serve an image/asset file from a doc source (core, Docs, or plugin). Path is relative to source root."""
        base_dir = self._get_source_base_dir(source_id)
        if not base_dir or not os.path.isdir(base_dir):
            abort(404)
        path_norm = os.path.normpath(asset_path.replace("\\", "/").lstrip("/")).replace("\\", "/")
        if path_norm.startswith("..") or "/.." in path_norm:
            abort(404)
        ext = os.path.splitext(path_norm)[1].lower()
        if ext not in DOC_ASSET_EXTENSIONS:
            abort(404)
        full_path = os.path.abspath(os.path.normpath(os.path.join(base_dir, path_norm)))
        base_abs = os.path.abspath(base_dir)
        if full_path != base_abs and not full_path.startswith(base_abs + os.sep):
            abort(404)
        if not os.path.isfile(full_path):
            abort(404)
        rel = os.path.relpath(full_path, base_dir).replace("\\", "/")
        return send_from_directory(base_dir, rel)

    def _get_doc_content_html(self, source_id: str, doc_path: str) -> Optional[Tuple[str, str]]:
        """Return (content_html, title) for embedding in home page, or None if not found. Uses same cache as view."""
        path_norm = os.path.normpath(doc_path).replace("\\", "/")
        if path_norm.startswith("..") or path_norm.startswith("/") or not path_norm.lower().endswith(".md"):
            return None
        entry = self._get_doc_entry(source_id, path_norm)
        if not entry or not os.path.isfile(entry["file_path"]):
            return None
        cache_key = (source_id, path_norm)
        if cache_key in self._html_cache:
            return self._html_cache[cache_key], entry["title"]
        with open(entry["file_path"], "r", encoding="utf-8") as f:
            text = f.read()
        current_file_dir = os.path.dirname(path_norm) or ""
        text = self._process_jekyll_links(text)
        text = self._process_markdown_file_links_for_source(text, source_id, current_file_dir)
        import markdown as markdown_lib
        html = markdown_lib.markdown(
            text,
            extensions=["fenced_code", "tables", "toc"],
            output_format="html5",
        )
        html = self._process_mermaid_blocks(html)
        html = self._process_markdown_links_for_source(html, source_id, current_file_dir)
        html = self._process_markdown_images_for_source(html, source_id, current_file_dir)
        self._html_cache[cache_key] = html
        return html, entry["title"]

    def _render_markdown_doc_by_source(self, source_id: str, doc_path: str):
        """Render a doc by (source_id, path). Uses index for path resolution and optional HTML cache."""
        path_norm = os.path.normpath(doc_path).replace("\\", "/")
        if path_norm.startswith("..") or path_norm.startswith("/"):
            abort(404)
        if not path_norm.lower().endswith(".md"):
            abort(404)

        entry = self._get_doc_entry(source_id, path_norm)
        if not entry:
            abort(404)
        file_path = entry["file_path"]
        if not os.path.isfile(file_path):
            abort(404)

        cache_key = (source_id, path_norm)
        if cache_key in self._html_cache:
            html = self._html_cache[cache_key]
            return render_template(
                "docs/view.html",
                content_html=html,
                filename=path_norm,
                source_id=source_id,
                doc_path=path_norm,
            )

        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        current_file_dir = os.path.dirname(path_norm)
        if current_file_dir == ".":
            current_file_dir = ""

        text = self._process_jekyll_links(text)
        text = self._process_markdown_file_links_for_source(text, source_id, current_file_dir)

        import markdown as markdown_lib

        html = markdown_lib.markdown(
            text,
            extensions=["fenced_code", "tables", "toc"],
            output_format="html5",
        )
        html = self._process_mermaid_blocks(html)
        html = self._process_markdown_links_for_source(html, source_id, current_file_dir)
        html = self._process_markdown_images_for_source(html, source_id, current_file_dir)
        self._html_cache[cache_key] = html

        return render_template(
            "docs/view.html",
            content_html=html,
            filename=path_norm,
            source_id=source_id,
            doc_path=path_norm,
        )

    def _render_markdown_doc(self, filename: str):
        """Legacy: render doc from Docs source only (backward compat)."""
        return self._render_markdown_doc_by_source("Docs", filename)
    
    def page(self, request):
        """Public page - redirects to admin"""
        return self.admin(request)
    
    def _process_jekyll_links(self, text):
        """Process Jekyll syntax {% link docs/... %} and replace with markdown links"""
        def replace_jekyll_link(match):
            jekyll_path = match.group(1)
            if jekyll_path.startswith('docs/'):
                jekyll_path = jekyll_path[5:]
            return f"]({jekyll_path})"
        text = re.sub(r'\{%\s*link\s+([^\s}]+)\s*%\}', replace_jekyll_link, text)
        return text

    def _resolve_doc_url(self, source_id: str, current_file_dir: str, link_url: str) -> Optional[str]:
        """Resolve relative .md link to URL if doc exists in index. Returns None if not found.
        Uses docs home URL (?category=&file=) so the link opens with the category tree on the left.
        Supports 'docs/name.md' from plugin root (e.g. README) -> finds name.md in plugin docs/."""
        if not link_url.lower().endswith(".md"):
            return None
        parsed = urlparse(link_url)
        if parsed.scheme or link_url.startswith("#"):
            return None
        if link_url.startswith("../"):
            target = os.path.normpath(os.path.join(current_file_dir, link_url)).replace("\\", "/")
        elif link_url.startswith("./"):
            target = os.path.normpath(os.path.join(current_file_dir, link_url[2:])).replace("\\", "/")
        else:
            target = os.path.normpath(os.path.join(current_file_dir, link_url)).replace("\\", "/")
        if target.startswith(".."):
            return None
        entry = self._get_doc_entry(source_id, target)
        if not entry and target.startswith("docs/"):
            entry = self._get_doc_entry(source_id, target[5:])
        if entry:
            return url_for("Docs.docs_home", category=source_id, file=entry["path"])
        return None

    def _process_markdown_file_links_for_source(self, text: str, source_id: str, current_file_dir: str) -> str:
        """Process markdown links and file mentions using index; resolve to docs_view_by_source URLs."""
        def replace_markdown_link(match):
            link_text, link_url = match.group(1), match.group(2)
            new_url = self._resolve_doc_url(source_id, current_file_dir, link_url)
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
            new_url = self._resolve_doc_url(source_id, current_file_dir, file_mention)
            if new_url:
                return f"[`{file_mention}`]({new_url})"
            return match.group(0)
        text = re.sub(r'`([^`]+\.md)`', replace_code_mention, text)
        def replace_plain(match):
            before, file_mention, after = match.group(1), match.group(2), match.group(3)
            if before and before.strip() and before.strip() in ["[", "`", "("]:
                return match.group(0)
            new_url = self._resolve_doc_url(source_id, current_file_dir, file_mention)
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

    def _process_markdown_file_links(self, text, current_file_dir):
        """Legacy: process markdown links for Docs source only (single docs_dir)."""
        return self._process_markdown_file_links_for_source(text, "Docs", current_file_dir)
    
    def _process_mermaid_blocks(self, html):
        """Process mermaid code blocks and convert to div.mermaid"""
        def process_mermaid_block(match):
            content = match.group(1)
            content = unescape(content)
            content = content.strip()
            return f'<div class="mermaid">{content}</div>'
        
        html = re.sub(
            r'<pre><code class="language-mermaid">(.*?)</code></pre>',
            process_mermaid_block,
            html,
            flags=re.DOTALL
        )
        html = re.sub(
            r'<pre><code class="mermaid">(.*?)</code></pre>',
            process_mermaid_block,
            html,
            flags=re.DOTALL
        )
        
        return html
    
    def _process_markdown_links_for_source(self, html_content: str, source_id: str, current_file_dir: str) -> str:
        """Process HTML links in rendered markdown; resolve .md to docs_view_by_source."""
        def replace_link_in_tag(match):
            before_href, link_url, after_href = match.group(1), match.group(2), match.group(3)
            new_url = self._resolve_doc_url(source_id, current_file_dir, link_url)
            if new_url:
                return f'<a{before_href}href="{new_url}"{after_href}>'
            return match.group(0)
        html_content = re.sub(
            r'<a([^>]*?)\s+href=["\']([^"\']+)["\']([^>]*)>',
            replace_link_in_tag,
            html_content,
        )
        return html_content

    def _resolve_asset_url(self, source_id: str, current_file_dir: str, image_url: str) -> Optional[str]:
        """Resolve relative image/asset URL to docs asset route URL. Returns None for external/data URLs."""
        parsed = urlparse(image_url)
        if parsed.scheme or image_url.strip().startswith("#"):
            return None
        path = image_url.strip()
        if path.startswith("./"):
            path = path[2:]
        if current_file_dir:
            target = os.path.normpath(os.path.join(current_file_dir, path)).replace("\\", "/")
        else:
            target = os.path.normpath(path).replace("\\", "/")
        if target.startswith("..") or "/.." in target:
            return None
        ext = os.path.splitext(target.split("?")[0])[1].lower()
        if ext not in DOC_ASSET_EXTENSIONS:
            return None
        return url_for("Docs.docs_asset_by_source", source_id=source_id, asset_path=target)

    def _process_markdown_images_for_source(self, html_content: str, source_id: str, current_file_dir: str) -> str:
        """Process <img src="..."> in HTML; resolve relative image URLs to docs asset route."""
        def replace_img_src(match):
            before, src, after = match.group(1), match.group(2), match.group(3)
            new_url = self._resolve_asset_url(source_id, current_file_dir, src)
            if new_url:
                return f'<img{before}src="{new_url}"{after}>'
            return match.group(0)
        html_content = re.sub(
            r'<img([^>]*?)\s+src=["\']([^"\']+)["\']([^>]*)>',
            replace_img_src,
            html_content,
        )
        return html_content

    def _process_markdown_links(self, html_content, current_file_dir):
        """Legacy: process HTML links for Docs source only."""
        return self._process_markdown_links_for_source(html_content, "Docs", current_file_dir)
