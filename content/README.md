# Content — Your Disclosure Documents

This is where you put documents that get published when the deadline passes.

---

## Quick Start

### 1. Create Your Document

Create a JSON file in `content/articles/`:

```json
{
    "time": 1707084000000,
    "version": "2.28.0",
    "blocks": [
        {"type": "header", "data": {"text": "My Title", "level": 1}},
        {"type": "paragraph", "data": {"text": "Your content here..."}}
    ]
}
```

### 2. Configure When It Publishes

Edit `content/manifest.yaml`:

```yaml
articles:
  - slug: my-document          # Matches filename (without .json)
    title: "My Document"
    visibility:
      min_stage: FULL          # Published at FULL stage
      include_in_nav: true     # Show in navigation
```

### 3. Build and Preview

```bash
./manage.sh  # Choose "build-site"
# or
python -m src.main build-site
open public/articles/my-document.html
```

---

## Directory Structure

```
content/
├── articles/                  # Your documents go here
│   ├── full_disclosure.json   # Example disclosure
│   └── about.json             # Example about page
├── manifest.yaml              # Controls what publishes when
└── README.md                  # This file
```

---

## Content Format

Documents use **Editor.js JSON format** — a block-based structure:

```json
{
    "blocks": [
        {"type": "header", "data": {"text": "Title", "level": 1}},
        {"type": "paragraph", "data": {"text": "Content..."}},
        {"type": "list", "data": {"style": "unordered", "items": ["A", "B", "C"]}}
    ]
}
```

### Supported Block Types

| Type | What it renders |
|------|-----------------|
| `header` | Heading (h1-h6) |
| `paragraph` | Text paragraph |
| `list` | Bullet or numbered list |
| `quote` | Block quote with caption |
| `table` | Data table |
| `code` | Code block |
| `warning` | Alert box |
| `delimiter` | Horizontal line |

### Inline Formatting

Inside text you can use:
- `<b>bold</b>`
- `<i>italic</i>`
- `<a href="...">links</a>`
- `<code>inline code</code>`

---

## Stage-Based Publishing

Control when content appears using `min_stage` in manifest.yaml:

| Stage | When | Effect |
|-------|------|--------|
| `OK` | Always visible | Like an "about" page |
| `WARNING` | After first escalation | Early warning content |
| `CRITICAL` | Urgent stage | Pre-disclosure content |
| `FULL` | After deadline passes | Main disclosure |

---

## Creating Content with Editor.js

For a visual editor experience:

1. Open https://editorjs.io/
2. Create your content
3. Click "Save" to get JSON
4. Copy into `content/articles/your-file.json`

---

## Example: Full Disclosure Document

See `content/articles/full_disclosure.json` for a complete example with:
- Headers
- Paragraphs
- Lists
- Tables
- Quotes
- Warning boxes

---

*Your content lives here. The system publishes it when the time comes.*
