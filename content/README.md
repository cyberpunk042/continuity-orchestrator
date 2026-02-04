# Content Directory — Editor.js Articles

This directory contains articles in **Editor.js JSON format**.

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    CONTENT PIPELINE                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   1. Author content using Editor.js                        │
│      (block-based editor)                                  │
│                      ↓                                      │
│   2. Save as JSON in content/articles/*.json               │
│                      ↓                                      │
│   3. Run `python -m src.main build-site`                   │
│                      ↓                                      │
│   4. EditorJSRenderer (src/site/editorjs.py)               │
│      converts JSON blocks → semantic HTML                   │
│                      ↓                                      │
│   5. SiteGenerator outputs to public/articles/*.html        │
│                      ↓                                      │
│   6. Deploy to GitHub Pages                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
content/
└── articles/
    ├── full_disclosure.json    # Main disclosure article
    ├── partial_notice.json     # Partial release notice
    └── about.json              # About page (optional)
```

## Editor.js JSON Format

Each file is a JSON object with:

```json
{
    "time": 1707084000000,
    "version": "2.28.0",
    "blocks": [
        {"type": "header", "data": {"text": "Title", "level": 1}},
        {"type": "paragraph", "data": {"text": "Content..."}}
    ]
}
```

## Supported Block Types

| Block Type | Description | Example |
|------------|-------------|---------|
| `header` | Headings h1-h6 | `{"level": 2, "text": "Section"}` |
| `paragraph` | Text paragraph | `{"text": "Hello world"}` |
| `list` | Ordered/unordered | `{"style": "ordered", "items": [...]}` |
| `quote` | Block quote | `{"text": "...", "caption": "Author"}` |
| `code` | Code block | `{"code": "print(1)", "language": "python"}` |
| `table` | Data table | `{"content": [[...], [...]], "withHeadings": true}` |
| `warning` | Alert box | `{"title": "Warning", "message": "..."}` |
| `delimiter` | Horizontal rule | `{}` |
| `image` | Image with caption | `{"url": "...", "caption": "..."}` |

## Inline Formatting

Within text content, you can use:
- `<b>bold</b>`
- `<i>italic</i>`
- `<a href="...">links</a>`
- `<code>inline code</code>`
- `<mark>highlight</mark>`

All other HTML is escaped for security.

## Adding a New Article

1. Create a JSON file in `content/articles/`:
   ```bash
   touch content/articles/my_article.json
   ```

2. Add Editor.js content:
   ```json
   {
       "time": 1707084000000,
       "version": "2.28.0",
       "blocks": [
           {"type": "header", "data": {"text": "My Article Title", "level": 1}},
           {"type": "paragraph", "data": {"text": "Article content goes here..."}}
       ]
   }
   ```

3. Build the site:
   ```bash
   python -m src.main build-site
   ```

4. View the result:
   ```bash
   open public/articles/my_article.html
   ```

## Using Editor.js to Author Content

For the authoring experience, you can use:

1. **Editor.js Demo**: https://editorjs.io/
2. **Local Editor**: Set up a simple HTML page with Editor.js

Example minimal editor:

```html
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.jsdelivr.net/npm/@editorjs/editorjs@latest"></script>
    <script src="https://cdn.jsdelivr.net/npm/@editorjs/header@latest"></script>
    <script src="https://cdn.jsdelivr.net/npm/@editorjs/list@latest"></script>
</head>
<body>
    <div id="editorjs"></div>
    <button onclick="save()">Save JSON</button>
    <pre id="output"></pre>
    
    <script>
        const editor = new EditorJS({
            holder: 'editorjs',
            tools: {
                header: Header,
                list: List
            }
        });
        
        function save() {
            editor.save().then(data => {
                document.getElementById('output').textContent = 
                    JSON.stringify(data, null, 2);
            });
        }
    </script>
</body>
</html>
```

## Security

- All text content is HTML-escaped by default
- Only whitelisted inline tags are preserved (`<b>`, `<i>`, `<a>`, `<code>`, `<mark>`)
- No raw HTML injection unless explicitly enabled
- No script execution possible

## Stage-Based Publishing

Articles can be linked to escalation stages in the plan:

```yaml
# policy/plans/default.yaml
stages:
  FULL:
    actions:
      - id: publish_full_article
        adapter: article_publish
        channel: public
        artifact:
          article: full_disclosure
```

When the system reaches `FULL` stage, the article is automatically included in the site build.
