# Editor.js — Minimal Article Editing & Rendering Pipeline

This document describes a **clean, free, JavaScript-only** setup to edit articles, store them as JSON, and render them safely inside an almost-empty HTML page.

The goal is:
- Word-like authoring experience
- Structured, diff-friendly storage
- Deterministic rendering
- Zero framework lock-in

---

## 1. What Editor.js Is

Editor.js is a block-based content editor.

Instead of producing HTML, it outputs **structured JSON**:

- paragraphs
- headings
- lists
- quotes
- code blocks
- embeds (optional)

This JSON becomes the **source of truth** for article content.

---

## 2. Data Model (What You Store)

Editor.js outputs a single JSON object:

- time: timestamp
- blocks: ordered array of content blocks
- version: editor version

Example (simplified):

- type: paragraph  
- data: text

This structure is:
- stable
- portable
- safe to store in DB, file, or API response
- easy to validate or sanitize

No HTML is stored.

---

## 3. Authoring Mode (Editor)

Used in admin / CMS / internal tools.

Core setup:
- Load Editor.js
- Enable only required tools
- Capture output via `save()`

Typical minimal toolset for articles:
- paragraph
- header
- list
- quote
- code

Result:
- clean authoring UI
- predictable output
- no inline styling chaos

---

## 4. Rendering Strategy A — JSON → DOM (Injected Script)

This is the **purest model**.

You render articles by **reloading Editor.js in read-only mode**.

### Page characteristics
- Almost empty HTML
- One container div
- One injected script
- CSS-only theming

### Behavior
- Load Editor.js
- Load the same tools
- Pass stored JSON as `data`
- Set `readOnly: true`

Editor.js becomes the **interpreter** for your content schema.

Advantages:
- Zero HTML generation
- Guaranteed consistency with editor output
- Easy upgrades

Tradeoff:
- Editor.js must be shipped to readers

---

## 5. Rendering Strategy B — JSON → HTML (Static Output)

Used when:
- You want static HTML
- You don’t want Editor.js on the frontend
- You want SSR or SSG

Approach:
- Parse Editor.js JSON
- Map blocks to HTML elements
- Inject result into content container

This can be:
- build-time
- server-side
- runtime (lightweight)

Advantages:
- No JS editor runtime on reader
- Very fast pages
- SEO-friendly

Tradeoff:
- You own the renderer
- You must keep mapping rules in sync

---

## 6. Styling Model

All styling is external.

Editor.js outputs **semantic structure only**:
- paragraphs → p
- headers → h1–h6
- lists → ul / ol
- quotes → blockquote

You control:
- typography
- spacing
- themes
- dark/light modes

No inline styles.
No editor artifacts.

---

## 7. Security & Control

Because content is JSON:
- No raw HTML injection
- No script execution
- No inline styles
- No XSS by default

You can:
- whitelist block types
- validate schema
- reject unsupported blocks
- version content safely

---

## 8. Where This Fits Well

Ideal for:
- documentation pages
- articles / blog posts
- course content
- CMS-lite systems
- static or hybrid sites
- systems that value structure over markup

---

## 9. Why This Is Better Than HTML Editors

HTML-based editors:
- mix content and presentation
- generate fragile markup
- are hard to diff or migrate

Editor.js:
- separates meaning from rendering
- treats content as data
- scales cleanly over time

---

## 10. Mental Model

Think of Editor.js content as:

- not a document
- not HTML
- not markdown

But as:
**a small, explicit content AST that you control**

---

## 11. Recommended Next Steps

- Lock down a minimal block set
- Define a content schema version
- Decide rendering strategy (A or B)
- Write a tiny reader template
- Theme purely via CSS

This becomes a long-term, low-maintenance content pipeline.
