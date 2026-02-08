# Content Authoring Guide

This guide explains how to create and manage content for Continuity Orchestrator.

---

## 📋 Overview

Content in Continuity Orchestrator is:

1. **Authored in Editor.js format** — JSON files in `content/articles/`
2. **Visibility-controlled** — Defined in `content/manifest.yaml`
3. **Rendered at build time** — Static HTML generated to `public/`

---

## 🏗️ File Structure

```
content/
├── manifest.yaml           # Visibility rules
├── articles/
│   ├── about.json          # Always visible (OK stage)
│   ├── notice.json         # Visible at PARTIAL+
│   └── full_disclosure.json # Visible at FULL only
└── README.md
```

---

## ✍️ Creating Articles

### Step 1: Create the JSON File

Create a file in `content/articles/` with `.json` extension:

```bash
touch content/articles/my_article.json
```

### Step 2: Write Editor.js Content

Editor.js uses a block-based structure:

```json
{
  "time": 1706886400000,
  "blocks": [
    {
      "id": "header1",
      "type": "header",
      "data": {
        "text": "Article Title",
        "level": 1
      }
    },
    {
      "id": "intro",
      "type": "paragraph",
      "data": {
        "text": "This is the introduction paragraph."
      }
    }
  ],
  "version": "2.28.0"
}
```

### Step 3: Register in Manifest

Add to `content/manifest.yaml`:

```yaml
articles:
  - slug: my_article      # Matches filename without .json
    title: "My Article"
    visibility:
      min_stage: PARTIAL  # When it becomes visible
      include_in_nav: true
      pin_to_top: false
    meta:
      description: "Brief description for SEO"
      author: "Author Name"
      tags: ["notice", "legal"]
```

---

## 📝 Supported Block Types

### Header

```json
{
  "type": "header",
  "data": {
    "text": "Section Title",
    "level": 2
  }
}
```

Levels: 1-6 (maps to h1-h6)

### Paragraph

```json
{
  "type": "paragraph",
  "data": {
    "text": "Regular paragraph text with <b>bold</b> and <i>italic</i> formatting."
  }
}
```

Supports inline HTML: `<b>`, `<i>`, `<u>`, `<a href="">`, `<code>`, `<mark>`

### List

```json
{
  "type": "list",
  "data": {
    "style": "unordered",
    "items": [
      "First item",
      "Second item",
      "Third item"
    ]
  }
}
```

Styles: `ordered` (numbered) or `unordered` (bullets)

### Code Block

```json
{
  "type": "code",
  "data": {
    "code": "function hello() {\n  console.log('Hello');\n}"
  }
}
```

### Quote

```json
{
  "type": "quote",
  "data": {
    "text": "This is a quoted statement.",
    "caption": "— Attribution"
  }
}
```

### Delimiter

```json
{
  "type": "delimiter",
  "data": {}
}
```

Renders as a horizontal rule (`<hr>`).

### Table

```json
{
  "type": "table",
  "data": {
    "withHeadings": true,
    "content": [
      ["Date", "Event", "Status"],
      ["2026-02-01", "Initial notice", "Sent"],
      ["2026-02-03", "Follow-up", "Pending"]
    ]
  }
}
```

### Warning/Alert

```json
{
  "type": "warning",
  "data": {
    "title": "Important",
    "message": "This section contains critical information."
  }
}
```

---

## 🎨 Inline Formatting

Within paragraph text, you can use:

| Format | HTML | Example |
|--------|------|---------|
| Bold | `<b>text</b>` | **text** |
| Italic | `<i>text</i>` | *text* |
| Underline | `<u>text</u>` | <u>text</u> |
| Code | `<code>text</code>` | `text` |
| Link | `<a href="url">text</a>` | [text](url) |
| Highlight | `<mark>text</mark>` | highlighted |

---

## 📊 Visibility Rules

### Stage Hierarchy

```
OK → REMIND_1 → REMIND_2 → PRE_RELEASE → PARTIAL → FULL
```

An article with `min_stage: PARTIAL` is visible at:
- ✅ PARTIAL
- ✅ FULL
- ❌ OK, REMIND_1, REMIND_2, PRE_RELEASE

### Navigation & Pinning

```yaml
visibility:
  min_stage: PARTIAL
  include_in_nav: true    # Show in navigation menu
  pin_to_top: true        # Display at top of article list (📌)
```

---

## 📄 Example Articles

### About Page (Always Visible)

`content/articles/about.json`:

```json
{
  "time": 1706886400000,
  "blocks": [
    {
      "id": "h1",
      "type": "header",
      "data": { "text": "About This System", "level": 1 }
    },
    {
      "id": "intro",
      "type": "paragraph",
      "data": {
        "text": "This automated system ensures continuity of important information."
      }
    },
    {
      "id": "how",
      "type": "header",
      "data": { "text": "How It Works", "level": 2 }
    },
    {
      "id": "desc",
      "type": "paragraph",
      "data": {
        "text": "The system operates on a countdown timer. If the timer is not renewed, escalation procedures begin automatically."
      }
    }
  ],
  "version": "2.28.0"
}
```

Manifest entry:

```yaml
- slug: about
  title: "About This System"
  visibility:
    min_stage: OK
    include_in_nav: true
    pin_to_top: false
```

### Disclosure Notice (FULL Stage)

`content/articles/full_disclosure.json`:

```json
{
  "time": 1706886400000,
  "blocks": [
    {
      "id": "h1",
      "type": "header",
      "data": { "text": "Full Disclosure Statement", "level": 1 }
    },
    {
      "id": "warning",
      "type": "warning",
      "data": {
        "title": "⚠️ Critical Notice",
        "message": "This information is being released due to failure to renew."
      }
    },
    {
      "id": "content",
      "type": "paragraph",
      "data": {
        "text": "The following information is now public domain..."
      }
    }
  ],
  "version": "2.28.0"
}
```

Manifest entry:

```yaml
- slug: full_disclosure
  title: "Full Disclosure Statement"
  visibility:
    min_stage: FULL
    include_in_nav: true
    pin_to_top: true     # 📌 Top of list when visible
```

---

## ✅ Best Practices

### ✓ Do

- Use descriptive, unique block IDs
- Keep articles focused on one topic
- Test locally with `python -m src.main build-site`
- Use semantic heading levels (h1 → h2 → h3)
- Include meta descriptions for SEO

### ✗ Don't

- Don't use external images (they must be self-contained)
- Don't include executable scripts
- Don't rely on external CDNs
- Don't skip heading levels (h1 → h3)

---

## 🔍 Testing Content

### Build the site

```bash
python -m src.main build-site
```

### View locally

Open `public/articles/index.html` in a browser.

### Check visibility

```bash
# See which articles are visible at current stage
python -c "
from src.site.manifest import ContentManifest
from src.persistence.state_file import load_state
from pathlib import Path

state = load_state(Path('state/current.json'))
manifest = ContentManifest.load()

print(f'Current stage: {state.escalation.state}')
print(f'Visible articles:')
for a in manifest.get_visible_articles(state.escalation.state):
    print(f'  - {a.slug}: {a.title}')
"
```

---

## 📚 Related Documentation

- [Configuration Guide](CONFIGURATION.md)
- [Content README](../content/README.md)
