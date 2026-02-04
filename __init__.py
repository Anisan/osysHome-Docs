"""Docs plugin - provides access to project documentation"""

import os
import re
from html import unescape
from urllib.parse import urlparse
from flask import abort, render_template, send_from_directory, url_for
from app.core.main.BasePlugin import BasePlugin
from app.configuration import Config
from app.authentication.handlers import handle_user_required


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
    
    def initialization(self):
        """Called when plugin starts"""
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

        docs_files = []
        
        if os.path.isdir(self.docs_dir):
            for filename in sorted(os.listdir(self.docs_dir)):
                if filename.endswith('.md'):
                    filepath = os.path.join(self.docs_dir, filename)
                    if os.path.isfile(filepath):
                        # Read first few lines for description
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                first_lines = f.read(200)
                                # Extract title if exists
                                title = filename.replace('.md', '').replace('_', ' ')
                                for line in first_lines.split('\n')[:5]:
                                    if line.startswith('# '):
                                        title = line[2:].strip()
                                        break
                                    elif line.startswith('## '):
                                        title = line[3:].strip()
                                        break
                        except Exception:
                            title = filename.replace('.md', '').replace('_', ' ')
                        
                        docs_files.append({
                            'filename': filename,
                            'title': title,
                            'url': url_for('Docs.docs_view', filename=filename)
                        })

        docs_dev_index = os.path.join(self.docs_dev_dir, "index.html")
        has_docs_dev = os.path.isfile(docs_dev_index)
        
        context = {
            'docs_files': docs_files,
            'title': self.title,
            'docs_dir': self.docs_dir,
            'docs_count': len(docs_files),
            'has_docs_dev': has_docs_dev,
            'status_ok': status_ok,
            'status_message': status_message,
        }
        return self.render("docs_admin.html", context)

    def route_docs(self):
        """Public docs routes (moved from core admin/routes.py)."""

        @self.blueprint.route("/docs")
        @self.blueprint.route("/docs/")
        @handle_user_required
        def docs_index():
            return docs_view("index.md")

        @self.blueprint.route("/docs/list")
        @handle_user_required
        def docs_list():
            files = self._get_docs_list()
            return render_template("docs/index.html", files=files)

        @self.blueprint.route("/docs/<path:filename>")
        @handle_user_required
        def docs_view(filename):
            return self._render_markdown_doc(filename)

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

    def _get_docs_list(self):
        if not os.path.isdir(self.docs_dir):
            return []
        files = []
        for name in os.listdir(self.docs_dir):
            if not name.lower().endswith(".md"):
                continue
            path = os.path.join(self.docs_dir, name)
            if not os.path.isfile(path):
                continue
            title = os.path.splitext(name)[0].replace("_", " ")
            files.append({"name": name, "title": title})
        files.sort(key=lambda x: x["name"].lower())
        return files

    def _render_markdown_doc(self, filename: str):
        safe_path = os.path.normpath(filename)
        if safe_path.startswith("..") or safe_path.startswith("/"):
            abort(404)

        if not safe_path.lower().endswith(".md"):
            return send_from_directory(self.docs_dir, safe_path)

        full_path = os.path.join(self.docs_dir, safe_path)
        if not os.path.isfile(full_path):
            abort(404)

        with open(full_path, "r", encoding="utf-8") as f:
            text = f.read()

        current_file_dir = os.path.dirname(safe_path).replace("\\", "/")
        if current_file_dir == ".":
            current_file_dir = ""

        text = self._process_jekyll_links(text)
        text = self._process_markdown_file_links(text, current_file_dir)

        import markdown as markdown_lib

        html = markdown_lib.markdown(
            text,
            extensions=["fenced_code", "tables", "toc"],
            output_format="html5",
        )

        html = self._process_mermaid_blocks(html)
        html = self._process_markdown_links(html, current_file_dir)
        return render_template("docs/view.html", content_html=html, filename=safe_path)
    
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
    
    def _process_markdown_file_links(self, text, current_file_dir):
        """Process markdown links [text](file.md) and replace paths with correct routes"""
        def replace_markdown_link(match):
            link_text = match.group(1)
            link_url = match.group(2)
            
            # Skip external links
            parsed = urlparse(link_url)
            if parsed.scheme or link_url.startswith('#'):
                return match.group(0)
            
            # Process only .md file links
            if not link_url.lower().endswith('.md'):
                return match.group(0)
            
            # Normalize path relative to current file
            if link_url.startswith('../'):
                normalized = os.path.normpath(os.path.join(current_file_dir, link_url))
                if normalized.startswith('..'):
                    return match.group(0)
                target_file = normalized
            elif link_url.startswith('./'):
                target_file = os.path.normpath(os.path.join(current_file_dir, link_url[2:]))
            else:
                target_file = os.path.normpath(os.path.join(current_file_dir, link_url))
            
            # Check if file exists
            full_target_path = os.path.join(self.docs_dir, target_file)
            if os.path.isfile(full_target_path):
                new_url = url_for('Docs.docs_view', filename=target_file.replace('\\', '/'))
                return f'[{link_text}]({new_url})'
            
            return match.group(0)
        
        # Process markdown links [text](url)
        text = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            lambda m: replace_markdown_link(m) if m.group(2).lower().endswith('.md') else m.group(0),
            text
        )
        
        # Process file mentions in backticks `file.md`
        def replace_code_mention(match):
            file_mention = match.group(1)
            if file_mention.lower().endswith('.md'):
                if file_mention.startswith('../'):
                    normalized = os.path.normpath(os.path.join(current_file_dir, file_mention))
                    if normalized.startswith('..'):
                        return match.group(0)
                    target_file = normalized
                elif file_mention.startswith('./'):
                    target_file = os.path.normpath(os.path.join(current_file_dir, file_mention[2:]))
                else:
                    target_file = os.path.normpath(os.path.join(current_file_dir, file_mention))
                
                full_target_path = os.path.join(self.docs_dir, target_file)
                if os.path.isfile(full_target_path):
                    new_url = url_for('Docs.docs_view', filename=target_file.replace('\\', '/'))
                    return f'[`{file_mention}`]({new_url})'
            
            return match.group(0)
        
        text = re.sub(r'`([^`]+\.md)`', replace_code_mention, text)
        
        # Process plain file mentions
        def replace_plain_file_mention_v2(match):
            before = match.group(1)
            file_mention = match.group(2)
            after = match.group(3)
            
            if before and before.strip() and before.strip() in ['[', '`', '(']:
                return match.group(0)
            
            if file_mention.startswith('../'):
                normalized = os.path.normpath(os.path.join(current_file_dir, file_mention))
                if normalized.startswith('..'):
                    return match.group(0)
                target_file = normalized
            elif file_mention.startswith('./'):
                target_file = os.path.normpath(os.path.join(current_file_dir, file_mention[2:]))
            else:
                target_file = os.path.normpath(os.path.join(current_file_dir, file_mention))
            
            full_target_path = os.path.join(self.docs_dir, target_file)
            if os.path.isfile(full_target_path):
                new_url = url_for('Docs.docs_view', filename=target_file.replace('\\', '/'))
                return f'{before}[{file_mention}]({new_url}){after}'
            
            return match.group(0)
        
        text = re.sub(
            r'(^|[\s\-:])([A-Za-z0-9_\-/]+\.md)([\s.,:;\)\]\n]|$)',
            replace_plain_file_mention_v2,
            text,
            flags=re.MULTILINE
        )
        
        return text
    
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
    
    def _process_markdown_links(self, html_content, current_file_dir):
        """Process HTML links in rendered markdown"""
        def replace_link_in_tag(match):
            before_href = match.group(1)
            link_url = match.group(2)
            after_href = match.group(3)
            
            parsed = urlparse(link_url)
            if parsed.scheme or link_url.startswith('#'):
                return match.group(0)
            
            if not link_url.lower().endswith('.md'):
                return match.group(0)
            
            if link_url.startswith('../'):
                normalized = os.path.normpath(os.path.join(current_file_dir, link_url))
                if normalized.startswith('..'):
                    return match.group(0)
                target_file = normalized
            elif link_url.startswith('./'):
                target_file = os.path.normpath(os.path.join(current_file_dir, link_url[2:]))
            else:
                target_file = os.path.normpath(os.path.join(current_file_dir, link_url))
            
            full_target_path = os.path.join(self.docs_dir, target_file)
            if os.path.isfile(full_target_path):
                new_href = url_for('Docs.docs_view', filename=target_file.replace('\\', '/'))
                return f'<a{before_href}href="{new_href}"{after_href}>'
            
            return match.group(0)
        
        html_content = re.sub(
            r'<a([^>]*?)\s+href=["\']([^"\']+)["\']([^>]*)>',
            replace_link_in_tag,
            html_content
        )
        
        return html_content
