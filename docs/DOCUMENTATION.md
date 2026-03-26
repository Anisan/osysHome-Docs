# Documentation Structure in Docs

Docs collects Markdown documents from several sources and shows them in one interface at `/docs`. This guide explains where files should live, how localization works, and which Markdown features are supported by the plugin.

---

## 1. Document Sources

Docs scans two source types in a fixed order:

| Source | Directory | Display name |
| --- | --- | --- |
| Core (OsysHome) | `<project_root>/docs/` | OsysHome |
| Plugins, including Docs | `plugins/<PluginName>/docs/` and selected root files | Plugin name |

For each plugin, Docs indexes:

- all `.md` files inside `plugins/<PluginName>/docs/`, including subdirectories;
- root files `README.md`, `README.ru.md`, `GetStarted.md`, and `GetStarted.ru.md` when they exist.

The index is built lazily on the first request to `/docs` or `/docs/search`. It can also be rebuilt from `/admin/Docs` with **Refresh index**. Rebuilds run in a background thread and do not block the UI.

---

## 2. File Names and Localization

- `Name.md` is the default document.
- `Name.XX.md` is a localized document where `XX` is the language code, for example `ru` or `en`.

Docs shows one visible entry per base name. If both `Users.md` and `Users.ru.md` exist, Russian users see `Users.ru.md`, while other locales fall back to `Users.md` unless a better match exists.

The document title is taken from the first level-1 heading (`# Title`). If there is no H1 heading, Docs uses the file name.

---

## 3. Categories in the UI

The left sidebar groups files by source:

1. `OsysHome` for files from the root `docs/` directory.
2. A plugin category such as `Docs`, `Users`, or `Tuya` for plugin documentation.

If a plugin provides `static/<PluginName>.png`, that file is used as the sidebar icon. Otherwise Docs falls back to a generic icon.

---

## 4. Links Between Documents

Docs processes several link types during Markdown rendering:

- Relative Markdown links such as `[Other](other.md)` or `[Guide](subfolder/doc.md)` are rewritten to internal Docs URLs.
- Links like `docs/Name.md` from a plugin root file are treated as files inside that plugin's `docs/` folder.
- External URLs with a protocol such as `https://example.com` stay external.
- Title attributes are supported: `[Text](url "Tooltip")`.
- Section anchors are supported: `[Jump](#section-name)`.

Jekyll-style links inside Markdown links are also supported:

```markdown
[Open docs]({% link docs/DOCUMENTATION.md %})
```

---

## 5. Images in Documentation

Basic syntax:

```markdown
![Alt text](images/screenshot.png)
```

Supported image scenarios:

- local paths relative to the current document;
- files from plugin `static/`, for example `../static/Docs.png`;
- external URLs;
- HTML `<img>` tags when you need explicit size or attributes.

Supported extensions include `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.ico`, and `.bmp`.

It is best to keep images next to the document that uses them or in a nearby `images/` subfolder.

---

## 6. Search and Cache

- `/docs/search` uses a Whoosh full-text index when `whoosh` is installed.
- Without Whoosh, Docs falls back to simpler substring matching.
- Search results can be returned as JSON with `?format=json`.
- Rendered HTML is cached in memory and invalidated when the index is rebuilt.
- The Whoosh index is stored in `cache/Docs/whoosh/`.

---

## 7. Developer API Documentation

The admin page includes a **Generate pdoc** action. It generates HTML API documentation from Python docstrings for active plugins and the core project, stores the result in `docs_dev/`, and serves it at `/docs_dev/`.

This is useful when you want browser-based API docs for plugin development without leaving the application.

---

## 8. Typical Layout

```text
<project_root>/
|-- docs/                              -> "OsysHome" category
|   |-- index.md
|   `-- guides/
|       `-- Setup.md
`-- plugins/
    |-- Docs/
    |   |-- README.md
    |   |-- README.ru.md
    |   `-- docs/
    |       |-- DOCUMENTATION.md
    |       |-- DOCUMENTATION.ru.md
    |       |-- MARKDOWN_SYNTAX_EXAMPLES.md
    |       `-- MARKDOWN_SYNTAX_EXAMPLES.ru.md
    `-- Tuya/
        |-- README.md
        |-- GetStarted.ru.md
        `-- docs/
            |-- Users.md
            `-- images/
                `-- screen.png
```

When a file is added or changed in one of these locations, Docs picks it up on the next lazy index build or after **Refresh index** is triggered in `/admin/Docs`.

---

## 9. Supported Markdown Features

Docs renders GitHub Flavored Markdown. For hands-on examples, see [MARKDOWN_SYNTAX_EXAMPLES.md](MARKDOWN_SYNTAX_EXAMPLES.md).

### Text and Formatting

| Element | Syntax |
| --- | --- |
| Headings | `#` to `######` |
| Bold | `**text**` or `__text__` |
| Italic | `*text*` or `_text_` |
| Strikethrough | `~~text~~` |
| Inline code | `` `code` `` |
| Subscript | `H<sub>2</sub>O` |
| Superscript | `x<sup>2</sup>` |
| Underline | `<ins>text</ins>` |

Line breaks are supported with two trailing spaces, a trailing `\`, or `<br/>`.

### Lists

- Unordered lists
- Ordered lists
- Task lists such as `- [x]` and `- [ ]`

### Code Blocks

- Plain fenced code blocks
- Language-aware blocks with syntax highlighting such as `python`, `javascript`, `json`, `yaml`, `bash`, and `sql`

### Tables

GitHub Flavored Markdown tables are supported, including left, center, and right alignment.

### Mermaid

Docs renders `mermaid` code blocks on the client side. Common diagram types include:

- `flowchart`
- `sequenceDiagram`
- `classDiagram`
- `stateDiagram-v2`
- `gantt`
- `erDiagram`
- `pie`

### Alerts and Extras

- Alerts such as `> [!NOTE]`, `> [!TIP]`, and `> [!WARNING]`
- Footnotes
- Color tokens in inline code
- Horizontal rules
- Inline HTML such as `<kbd>`, `<abbr>`, `<sub>`, `<sup>`, `<ins>`, and `<img>`
- Escaped special characters
- Hidden HTML comments
