"""Docs plugin - provides access to project documentation"""

import os
import json
from datetime import datetime
from threading import Lock, Thread
from typing import List, Dict, Any, Optional, Tuple

from flask import abort, jsonify, redirect, render_template, request, send_from_directory, url_for
from app.core.main.BasePlugin import BasePlugin
from app.core.lib.cache import existInCache, getCacheDir, getFullFilename, saveToCache
from app.authentication.handlers import handle_user_required

from plugins.Docs.constants import DOC_ASSET_EXTENSIONS
from plugins.Docs.markdown_converter import get_markdown_converter
from plugins.Docs.markdown_processor import (
    process_jekyll_links,
    process_mermaid_blocks,
    process_code_blocks_for_prism,
    process_github_alerts,
    process_color_swatches,
    LinkResolver,
)
from plugins.Docs import indexer

try:
    from app import safe_translate
except ImportError:
    safe_translate = lambda x: x


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

        self.docs_dir = os.path.join(os.path.dirname(__file__), "docs")
        self.project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
        )
        self.docs_dev_dir = os.path.join(self.project_root, "docs_dev")
        self.plugins_dir = os.path.join(self.project_root, "plugins")

        self._docs_index: List[Dict[str, Any]] = []
        self._html_cache: Dict[Tuple[str, str], str] = {}
        self._doc_entry_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._docs_by_source: Dict[str, List[Dict[str, Any]]] = {}
        self._category_docs_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._whoosh_index_dir = os.path.join(getCacheDir(), "Docs", "whoosh")
        self._index_built_at: Optional[datetime] = None
        self._index_build_lock = Lock()
        self._index_build_thread: Optional[Thread] = None
        self._progress_filename = "index_progress.json"
        self._link_resolver: Optional[LinkResolver] = None

    def _get_link_resolver(self) -> LinkResolver:
        if self._link_resolver is None:
            self._link_resolver = LinkResolver(
                get_doc_entry=self._get_doc_entry,
                url_for=url_for,
            )
        return self._link_resolver

    def _normalize_doc_path(self, path: str) -> str:
        return os.path.normpath(path).replace("\\", "/")

    def _get_doc_entry(self, source_id: str, path: str) -> Optional[Dict[str, Any]]:
        path_norm = self._normalize_doc_path(path)
        entry = self._doc_entry_map.get((source_id, path_norm))
        if entry:
            return entry
        return indexer.get_doc_entry(self._docs_index, source_id, path_norm)

    def _ensure_index_started(self) -> bool:
        if self._docs_index:
            return True
        self._start_index_rebuild_async()
        return False

    def initialization(self):
        """Called when plugin starts."""
        try:
            _, name = get_markdown_converter()
            self.logger.info("Docs plugin initialized (Markdown: %s)", name)
        except ImportError as e:
            self.logger.warning("Docs plugin: no Markdown converter: %s", e)
        self._start_index_rebuild_async()

    def admin(self, request):
        """Admin page - shows documentation index."""
        status_message = None
        status_ok = None

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

        self._ensure_index_started()

        docs_dev_index = os.path.join(self.docs_dev_dir, "index.html")
        has_docs_dev = os.path.isfile(docs_dev_index)

        context = {
            "title": self.title,
            "has_docs_dev": has_docs_dev,
            "status_ok": status_ok,
            "status_message": status_message,
            "index_info": indexer.get_index_info(self),
            "index_progress": self._get_index_progress(),
        }
        return self.render("docs_admin.html", context)

    def route_docs(self):
        """Public docs routes."""

        @self.blueprint.route("/docs/asset/<source_id>/<path:asset_path>")
        @handle_user_required
        def docs_asset_by_source(source_id, asset_path):
            return self._serve_doc_asset(source_id, asset_path)

        @self.blueprint.route("/docs")
        @self.blueprint.route("/docs/")
        @handle_user_required
        def docs_home():
            index_ready = self._ensure_index_started()
            try:
                from app import get_current_language
                locale = get_current_language() or "en"
            except Exception:
                locale = "en"
            categories = indexer.get_home_categories(self)
            selected_id = request.args.get("category", "").strip() or (categories[0]["source_id"] if categories else "")
            if selected_id and not any(c["source_id"] == selected_id for c in categories):
                selected_id = categories[0]["source_id"] if categories else ""
            selected_file = request.args.get("file", "").strip()
            tree = []
            for cat in categories:
                docs = indexer.get_documents_for_category(self, cat["source_id"], locale)
                tree.append({
                    "source_id": cat["source_id"],
                    "heading": cat["heading"],
                    "icon_url": cat["icon_url"],
                    "documents": docs,
                })
            doc_content_html = None
            doc_title = None
            if selected_id and selected_file:
                content_result = self._get_doc_content_html(selected_id, selected_file, locale)
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
                index_ready=index_ready,
                index_progress=self._get_index_progress(),
            )

        @self.blueprint.route("/docs/<source_id>/<path:doc_path>")
        @handle_user_required
        def docs_view_by_source(source_id, doc_path):
            return self._render_markdown_doc_by_source(source_id, doc_path)

        @self.blueprint.route("/docs/search")
        @handle_user_required
        def docs_search():
            q = (request.args.get("q") or "").strip()
            index_ready = self._ensure_index_started()
            try:
                from app import get_current_language
                locale = get_current_language() or "en"
            except Exception:
                locale = "en"
            results = indexer.search_docs(self, q, locale) if q and index_ready else []
            if request.args.get("format") == "json":
                return jsonify({
                    "query": q,
                    "index_ready": index_ready,
                    "results": [
                        {"title": r["title"], "url": r["url"], "source_id": r["source_id"], "path": r["path"]}
                        for r in results
                    ],
                })
            categories = indexer.get_home_categories(self)
            tree = []
            for cat in categories:
                docs = indexer.get_documents_for_category(self, cat["source_id"], locale)
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
                index_ready=index_ready,
                index_progress=self._get_index_progress(),
            )

        @self.blueprint.route("/docs/index_status")
        @handle_user_required
        def docs_index_status():
            return jsonify({
                "index_info": indexer.get_index_info(self),
                "index_progress": self._get_index_progress(),
            })

        @self.blueprint.route("/docs/<path:filename>")
        @handle_user_required
        def docs_view_legacy(filename):
            safe = os.path.normpath(filename)
            if safe.startswith("..") or safe.startswith("/"):
                abort(404)
            if safe.lower().endswith(".md"):
                return redirect(url_for("Docs.docs_home", category="Docs", file=safe))
            abort(404)

    def route_docs_dev(self):
        """Developer docs (pdoc) routes."""

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
        """List names of enabled (active) plugins only."""
        try:
            from app.core.main.PluginsHelper import plugins
            names = list(plugins.keys())
        except Exception:
            names = []
        names.sort(key=lambda s: s.lower())
        return names

    def _start_index_rebuild_async(self) -> bool:
        """Start index rebuild in a background thread."""
        with self._index_build_lock:
            if self._index_build_thread and self._index_build_thread.is_alive():
                return False

            def run():
                try:
                    indexer.build_docs_index(self)
                except Exception as ex:
                    self.logger.exception(ex)
                    self._set_index_progress(
                        status="error", phase="error", processed=None, total=None, message=str(ex)
                    )

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
        """Serve an image/asset file from a doc source."""
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
        if not os.path.isfile(full_path) and source_id == "Docs":
            plugin_root = os.path.dirname(base_dir)
            fallback_path = os.path.abspath(os.path.normpath(os.path.join(plugin_root, path_norm)))
            plugin_abs = os.path.abspath(plugin_root)
            if fallback_path.startswith(plugin_abs + os.sep) and os.path.isfile(fallback_path):
                full_path = fallback_path
                base_dir = plugin_root
                base_abs = plugin_abs
        if not os.path.isfile(full_path):
            abort(404)
        rel = os.path.relpath(full_path, base_dir).replace("\\", "/")
        return send_from_directory(base_dir, rel)

    def _get_doc_content_html(self, source_id: str, doc_path: str, locale: str = "en") -> Optional[Tuple[str, str]]:
        """Return (content_html, title) for embedding in home page, or None if not found."""
        path_norm = self._normalize_doc_path(doc_path)
        if path_norm.startswith("..") or path_norm.startswith("/") or not path_norm.lower().endswith(".md"):
            return None
        entry = self._get_doc_entry(source_id, path_norm)
        if not entry or not os.path.isfile(entry["file_path"]):
            return None
        cache_key = (source_id, path_norm, locale)
        if cache_key in self._html_cache:
            return self._html_cache[cache_key], entry["title"]
        translate_fn = lambda k: safe_translate(k, locale)
        with open(entry["file_path"], "r", encoding="utf-8") as f:
            text = f.read()
        current_file_dir = os.path.dirname(path_norm) or ""
        text = process_jekyll_links(text)
        resolver = self._get_link_resolver()
        text = resolver.process_markdown_file_links(text, source_id, current_file_dir)
        convert, _ = get_markdown_converter()
        html = convert(text)
        html = process_mermaid_blocks(html)
        html = process_code_blocks_for_prism(html)
        html = process_github_alerts(html, translate=translate_fn)
        html = process_color_swatches(html)
        html = resolver.process_markdown_links(html, source_id, current_file_dir)
        html = resolver.process_markdown_images(html, source_id, current_file_dir)
        self._html_cache[cache_key] = html
        return html, entry["title"]

    def _render_markdown_doc_by_source(self, source_id: str, doc_path: str):
        """Render a doc by (source_id, path)."""
        try:
            from app import get_current_language
            locale = get_current_language() or "en"
        except Exception:
            locale = "en"
        if not self._ensure_index_started():
            return redirect(url_for("Docs.docs_home", category=source_id, file=doc_path))
        path_norm = self._normalize_doc_path(doc_path)
        if path_norm.startswith("..") or path_norm.startswith("/"):
            abort(404)
        if not path_norm.lower().endswith(".md"):
            abort(404)

        entry = self._get_doc_entry(source_id, path_norm)
        if not entry:
            abort(404)
        if not os.path.isfile(entry["file_path"]):
            abort(404)

        cache_key = (source_id, path_norm, locale)
        if cache_key in self._html_cache:
            return render_template(
                "docs/view.html",
                content_html=self._html_cache[cache_key],
                filename=path_norm,
                source_id=source_id,
                doc_path=path_norm,
            )

        translate_fn = lambda k: safe_translate(k, locale)
        with open(entry["file_path"], "r", encoding="utf-8") as f:
            text = f.read()

        current_file_dir = os.path.dirname(path_norm)
        if current_file_dir == ".":
            current_file_dir = ""

        text = process_jekyll_links(text)
        resolver = self._get_link_resolver()
        text = resolver.process_markdown_file_links(text, source_id, current_file_dir)
        convert, _ = get_markdown_converter()
        html = convert(text)
        html = process_mermaid_blocks(html)
        html = process_code_blocks_for_prism(html)
        html = process_github_alerts(html, translate=translate_fn)
        html = process_color_swatches(html)
        html = resolver.process_markdown_links(html, source_id, current_file_dir)
        html = resolver.process_markdown_images(html, source_id, current_file_dir)
        self._html_cache[cache_key] = html

        return render_template(
            "docs/view.html",
            content_html=html,
            filename=path_norm,
            source_id=source_id,
            doc_path=path_norm,
        )

    def page(self, request):
        """Public page - redirects to admin."""
        return self.admin(request)
