# Project Improvement Plan

## 1. Fix 10 Failing Tests
- Content route tests: mock `get_encryption_key` directly instead of just env
- Media API: update expected values for `_id_prefix_for_mime`, delete, preview
- Media optimize: update threshold expectation

## 2. Extract Workflow Inline Python → Script
- Move stuck deployment cleanup to `scripts/clear_stuck_deployments.py`
- Call from all 3 workflows

## 3. Split `_wizard.html` — Modals into Own Folder
- Create `src/admin/templates/modals/` folder
- Extract modal dialogs into individual files  
- Include them via Jinja2 `{% include %}`

## 4. Fix File Permission Handling
- Add ownership/permission checks in backup/restore
- Graceful errors instead of crashes

## 5. Standardize Python Version
- Update `pyproject.toml` to `requires-python = ">=3.11"`
- Keep `target-version = "py311"`

## 6. Add mypy/ruff to CI
- Add linting step to `test.yml` workflow

## 7. Split Large Route Files  
- `routes_media.py` → upload + manage modules
- Consider `routes_content.py` split

## Status
- [x] Tests fixed (639/639 passing)
- [x] Workflow script extracted (scripts/clear_stuck_deployments.py)
- [x] Wizard modals split (4 modals → modals/ folder)
- [ ] Permission handling
- [ ] Python version
- [ ] CI linting
- [ ] Route file splits
