# Site Generator Improvements Plan

## 1. Fix Placeholders (Quick Wins)

### `example.com` references:
- [ ] `src/main.py:599` - `operator@example.com` default
- [ ] `src/main.py:1094` - example in help text (OK to keep)
- [ ] `src/site/generator.py:383` - RSS feed link placeholder

### `owner/repo` defaults:
- Most are OK (defaults/documentation), but:
- [ ] `state/current.json:55` - Should be updated to actual repo
- [ ] `countdown.html` files in root - stale build artifacts, should be gitignored

## 2. Generator Refactoring

Current `generator.py` is 1564 lines. Extract into:

```
src/site/
├── generator.py          # Main orchestration (build method)
├── context.py            # _build_context logic
├── pages/
│   ├── index.py          # _generate_index
│   ├── countdown.py      # _generate_countdown (728 lines!)
│   ├── timeline.py       # _generate_timeline
│   ├── status.py         # _generate_status, _generate_status_json
│   ├── feed.py           # _generate_feed
│   └── articles.py       # _generate_articles, _generate_articles_index
├── templates/
│   └── base.py           # _render_html_page with common styles
└── editorjs.py           # Already extracted
```

## 3. Countdown Page Improvements

### Show Release Status:
- [ ] Display what content has been released at each stage
- [ ] Show disclosure timeline (what triggers when)
- [ ] Visual progress bar showing escalation path

### Integration Status Dashboard:
- [ ] Show which integrations are enabled
- [ ] Last execution time for each
- [ ] Success/failure status from audit log
- [ ] Retry counts if applicable

### Escalation Visibility:
- [ ] Current stage with clear explanation
- [ ] What happens at next stage
- [ ] Time until next escalation

## 4. Integration Tracking

### Audit Log Enhancements:
- [ ] Parse audit log for integration execution details
- [ ] Track: adapter name, trigger time, success/fail, error message
- [ ] Group by tick for timeline view

### Site Display:
- [ ] "Integration Status" card on status page
- [ ] Badge showing last execution per adapter
- [ ] Error details if any failed

## 5. RSS Feed Fix

Replace `https://example.com/` with actual GitHub Pages URL:
```python
github_repo = context.get("github_repository", "")
if github_repo:
    site_url = f"https://{github_repo.split('/')[0]}.github.io/{github_repo.split('/')[1]}/"
```

## Priority Order

1. **Fix RSS feed link** (5 min)
2. **Fix operator@example.com default** (5 min)  
3. **Add integration status to status page** (30 min)
4. **Countdown page improvements** (1 hour)
5. **Generator refactoring** (2 hours) - later, not urgent
