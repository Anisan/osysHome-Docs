# Docs - Documentation Viewer

![Docs Icon](static/Docs.png)

A built-in documentation system that collects, indexes, and displays Markdown documentation from across the project in a unified web interface with full-text search.

## Description

The `Docs` module aggregates all Markdown files from the project's `docs/` folder and from every active plugin's `docs/` folder and root README/GetStarted files. It renders them in a two-column browser with a category tree on the left and formatted document content on the right. Full-text search is powered by Whoosh with Russian and English morphological analysis.

## Main Features

- **Unified documentation viewer** at `/docs` — accordion sidebar with all categories and documents
- **Full-text search** at `/docs/search` — Whoosh-based index with Russian morphology (lemmatization), falls back to substring match if Whoosh is not installed
- **Automatic content discovery** — scans `docs/` at project root (category "OsysHome") and `plugins/<Name>/docs/` + root `README.md`, `README.ru.md`, `GetStarted.md`, `GetStarted.ru.md` for every active plugin
- **Multilingual support** — one entry per document base name, language chosen automatically by system locale (`Name.ru.md`, `Name.en.md`, `Name.md` as default)
- **Mermaid diagrams** — `mermaid` code blocks are rendered client-side with dark-mode support
- **Relative link resolution** — `.md` links in documents are automatically rewritten to internal Docs URLs
- **Image proxy** — relative image paths are served through the asset route (`/docs/<source>/asset/<path>`)
- **HTML rendering cache** — rendered HTML is cached in memory; invalidated on index rebuild
- **Async index rebuild** — "Refresh index" runs in a background thread without blocking the UI
- **Developer API docs** — optional pdoc-based HTML API documentation at `/docs_dev/` (generated on demand from the admin panel)
- **Progress tracking** — index build progress is polled live in the admin panel via `/docs/index_status`

## Admin Panel

The admin panel at `/admin/Docs` provides:

- **Index status**: total document count, per-source breakdown, last build timestamp
- **Whoosh status**: installed / ready / index directory / file count and size
- **Refresh index** — triggers an async rebuild of the document index and Whoosh FTS index
- **Generate pdoc** — generates developer API documentation for all active plugins into `docs_dev/` and makes it available at `/docs_dev/`

## Web Interface

### Main Docs Browser (`/docs`)

- Left sidebar with an accordion tree: each category (source) shows its icon, document count badge, and an expandable list of documents
- Live filter input that narrows categories and files by name in real time
- Sidebar accordion state is persisted to `localStorage` across page reloads
- Right panel displays the selected document rendered from Markdown, or a category document list if no file is selected
- "Open in new tab" button for every open document
- Mermaid.js loaded from CDN only when a document is open

### Search (`/docs/search`)

- Same left sidebar as the main browser
- Search form with real-time result list: title, highlighted snippet, and `source / path` breadcrumb
- Returns JSON when `?format=json` is appended (useful for integrations)

## Documentation Sources

| Source | Directory | Sidebar category |
|--------|-----------|-----------------|
| Core (OsysHome) | `<project_root>/docs/` | OsysHome |
| Plugin | `plugins/<Name>/docs/` + root `README*.md` / `GetStarted*.md` | Plugin name |

## Document Naming and Localization

| File name | Language |
|-----------|----------|
| `Name.md` | Default (shown for any locale without a better match) |
| `Name.ru.md` | Russian |
| `Name.en.md` | English |

The system shows one document per base name. For the current locale it prefers the exact language match, then falls back to the default file.

## Adding Documentation

See [DOCUMENTATION.md](docs/DOCUMENTATION.md) for a full guide on placing documents, file naming conventions, localization, cross-document links, and images.

## File Structure

```
plugins/Docs/
├── __init__.py               — Main plugin class
├── pdoc_generator.py         — Developer API docs generation via pdoc
├── requirements.txt          — Python dependencies
├── static/
│   └── Docs.png              — Plugin icon
├── docs/
│   └── DOCUMENTATION.md      — Documentation authoring guide
├── templates/
│   ├── docs_admin.html       — Admin panel (/admin/Docs)
│   └── docs/
│       ├── home.html         — Main docs browser (/docs)
│       ├── search.html       — Search page (/docs/search)
│       └── view.html         — Standalone view (legacy, redirects to home)
└── translations/
    ├── en.json               — English UI strings
    └── ru.json               — Russian UI strings
```

## Routes

| Route | Description |
|-------|-------------|
| `GET /docs` | Main docs browser |
| `GET /docs/search` | Full-text search page |
| `GET /docs/search?format=json` | Search results as JSON |
| `GET /docs/<source>/<path>` | Redirect to docs browser with that document selected |
| `GET /docs/<source>/asset/<path>` | Asset (image) proxy for docs |
| `GET /docs/index_status` | JSON index status endpoint (polled by admin panel) |
| `GET /docs_dev/` | Developer API docs (pdoc-generated HTML) |

## Technical Details

- **Index**: built lazily on first access to `/docs` or `/docs/search`; can be manually triggered from admin panel
- **Whoosh FTS**: pure-Python full-text engine; index stored in `cache/Docs/whoosh/`; supports Russian (`ru`) and English (`en`) language analyzers with morphological stemming
- **Markdown rendering**: `python-markdown` with `fenced_code`, `tables`, and `toc` extensions
- **Mermaid**: `mermaid` code blocks are converted to `<div class="mermaid">` rendered client-side via CDN
- **Thread safety**: index rebuild runs in a daemon thread; build progress written to `cache/Docs/index_progress.json`

## Requirements

- `markdown` — Markdown rendering
- `whoosh>=2.7.0` — Full-text search (optional; search falls back to substring matching without it)
- `pdoc` — Developer API docs generation (optional; used only by the "Generate pdoc" admin action)

## Version

Current version: **1**

## Category

System

## Author

osysHome
