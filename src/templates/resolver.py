"""
Template Resolver — Load and render template content.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class TemplateResolver:
    """
    Resolves and renders templates for adapter payloads.

    Templates are located by name in the templates directory.
    Variables are substituted using ${{variable}} syntax.
    """

    # Directories to search, in order
    SEARCH_ORDER = [
        "operator",
        "custodians",
        "public",
        "articles",
        "",  # Root
    ]

    # Supported extensions, in order of preference
    EXTENSIONS = [".md", ".txt", ".html"]

    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir

    def resolve(self, template_name: str) -> Optional[Path]:
        """
        Find a template file by name.

        Searches in multiple directories and extensions.
        Returns the first match or None.
        """
        for subdir in self.SEARCH_ORDER:
            base_path = self.templates_dir / subdir if subdir else self.templates_dir
            if not base_path.exists():
                continue

            for ext in self.EXTENSIONS:
                candidate = base_path / f"{template_name}{ext}"
                if candidate.exists():
                    logger.debug(f"Resolved template '{template_name}' to {candidate}")
                    return candidate

        logger.warning(f"Template '{template_name}' not found in {self.templates_dir}")
        return None

    def load(self, template_name: str) -> Optional[str]:
        """Load a template's content by name."""
        path = self.resolve(template_name)
        if path is None:
            return None

        with path.open(encoding="utf-8") as f:
            return f.read()

    def render(self, template_content: str, context: Dict[str, Any]) -> str:
        """
        Render a template with variable substitution.

        Variables use the syntax ${{variable_name}}.
        Nested access uses dots: ${{meta.project}}.

        Missing variables are replaced with empty string and logged.
        """

        def replace_var(match: re.Match) -> str:
            var_path = match.group(1).strip()
            value = self._get_nested(context, var_path)

            if value is None:
                logger.warning(f"Template variable not found: {var_path}")
                return ""

            return str(value)

        # Match ${{...}} pattern
        pattern = r"\$\{\{([^}]+)\}\}"
        return re.sub(pattern, replace_var, template_content)

    def _get_nested(self, obj: Any, path: str) -> Any:
        """Get a value from nested dicts using dot notation."""
        parts = path.split(".")
        current = obj

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return None

            if current is None:
                return None

        return current

    def resolve_and_render(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        Convenience method to load and render in one step.
        """
        content = self.load(template_name)
        if content is None:
            return None
        return self.render(content, context)
