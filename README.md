# Docs - Documentation Viewer

![Docs Icon](static/Docs.png)

`Docs` is the built-in documentation browser for osysHome. It collects Markdown files from the project and active plugins, indexes them, and serves them through a single web UI with search.

## Description

The plugin scans the root `docs/` directory and documentation files from every active plugin. It groups them by source, renders Markdown to HTML, resolves internal links and images, and exposes everything through `/docs` and `/docs/search`.

## Main Features

- Unified documentation browser at `/docs`
- Full-text search at `/docs/search`
- Automatic discovery of project and plugin documentation
- Per-document language selection using locale-aware file matching
- Mermaid diagram rendering
- Relative link rewriting for `.md` files
- Asset proxy for local images used inside documentation
- In-memory HTML cache with rebuild invalidation
- Background index rebuild from the admin page
- Optional developer API documentation generated with `pdoc`

## Admin Panel

The admin page at `/admin/Docs` provides:

- index status and document counts;
- Whoosh status;
- asynchronous index rebuild;
- `pdoc` generation for developer API docs.

## Web Interface

### Main Browser (`/docs`)

- Left sidebar with sources and documents
- Live filter for categories and file names
- Persistent accordion state in `localStorage`
- Rendered document view on the right
- "Open in new tab" action for the active document
- Mermaid loaded only when needed

### Search (`/docs/search`)

- Same sidebar as the main browser
- Search results with title, snippet, and source path
- JSON output with `?format=json`

## Documentation Sources

| Source | Directory | Sidebar category |
| --- | --- | --- |
| Core (OsysHome) | `<project_root>/docs/` | OsysHome |
| Plugin | `plugins/<Name>/docs/` plus root `README*.md` and `GetStarted*.md` | Plugin name |

## Document Naming and Localization

| File name | Meaning |
| --- | --- |
| `Name.md` | Default version |
| `Name.ru.md` | Russian version |
| `Name.en.md` | English version |

For one base name, Docs shows the best match for the active locale and falls back to the default file when no exact language file exists.

## Adding Documentation

See [DOCUMENTATION.md](docs/DOCUMENTATION.md) for the documentation structure guide and [MARKDOWN_SYNTAX_EXAMPLES.md](docs/MARKDOWN_SYNTAX_EXAMPLES.md) for supported Markdown examples.

Russian versions are also available:

- [DOCUMENTATION.ru.md](docs/DOCUMENTATION.ru.md)
- [MARKDOWN_SYNTAX_EXAMPLES.ru.md](docs/MARKDOWN_SYNTAX_EXAMPLES.ru.md)

## File Structure

```text
plugins/Docs/
|-- __init__.py
|-- pdoc_generator.py
|-- requirements.txt
|-- static/
|   `-- Docs.png
|-- docs/
|   |-- DOCUMENTATION.md
|   |-- DOCUMENTATION.ru.md
|   |-- MARKDOWN_SYNTAX_EXAMPLES.md
|   `-- MARKDOWN_SYNTAX_EXAMPLES.ru.md
|-- templates/
|   |-- docs_admin.html
|   `-- docs/
|       |-- home.html
|       |-- search.html
|       `-- view.html
`-- translations/
    |-- en.json
    `-- ru.json
```

## Routes

| Route | Description |
| --- | --- |
| `GET /docs` | Main docs browser |
| `GET /docs/search` | Full-text search page |
| `GET /docs/search?format=json` | Search results as JSON |
| `GET /docs/<source>/<path>` | Open a specific document in the browser |
| `GET /docs/asset/<source>/<path>` | Serve documentation assets |
| `GET /docs/index_status` | JSON index status endpoint |
| `GET /docs_dev/` | Generated developer API docs |

## Technical Details

- Indexes are built lazily on first access or manually from the admin panel.
- Whoosh stores its index in `cache/Docs/whoosh/`.
- Markdown rendering uses `cmarkgfm` or `markdown2`.
- Mermaid blocks are rendered client-side.
- Rebuild progress is written to `cache/Docs/index_progress.json`.

## Requirements

- `cmarkgfm` or `markdown2` for Markdown rendering
- `whoosh>=2.7.0` for full-text search
- `pdoc` for optional developer API documentation

## Version

Current version: **1**

## Category

System

## Author

osysHome
