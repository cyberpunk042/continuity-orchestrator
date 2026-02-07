"""
Content Manifest — Load and validate article visibility rules.

The manifest defines which articles are published at which escalation stage.
Articles only become visible when the system reaches their minimum stage.

## Usage

    from src.site.manifest import ContentManifest
    
    manifest = ContentManifest.load()
    visible_articles = manifest.get_visible_articles("PARTIAL")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Stage order for comparison
STAGE_ORDER = {
    "OK": 0,
    "REMIND_1": 10,
    "REMIND_2": 20,
    "PRE_RELEASE": 30,
    "PARTIAL": 40,
    "FULL": 50,
}


@dataclass
class ArticleVisibility:
    """Visibility settings for an article."""
    
    min_stage: str = "FULL"
    include_in_nav: bool = False
    pin_to_top: bool = False
    
    @property
    def min_stage_order(self) -> int:
        """Get numeric order of minimum stage."""
        return STAGE_ORDER.get(self.min_stage, 50)


@dataclass
class ArticleMeta:
    """Metadata for an article."""
    
    description: Optional[str] = None
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class ArticleEntry:
    """Entry in the content manifest."""
    
    slug: str
    title: str
    visibility: ArticleVisibility
    meta: ArticleMeta = field(default_factory=ArticleMeta)
    
    def is_visible_at(self, stage: str) -> bool:
        """Check if article is visible at given stage."""
        current_order = STAGE_ORDER.get(stage, 0)
        return current_order >= self.visibility.min_stage_order


@dataclass
class StageBehavior:
    """Site behavior settings for a specific stage."""
    
    show_countdown: bool = True
    show_articles: bool = False
    banner: Optional[str] = None
    banner_class: Optional[str] = None


@dataclass
class DefaultVisibility:
    """Default visibility for unlisted articles."""
    
    min_stage: str = "FULL"
    include_in_nav: bool = False
    pin_to_top: bool = False


class ContentManifest:
    """
    Load and query the content manifest.
    
    The manifest defines which articles are visible at which stages.
    """
    
    def __init__(
        self,
        articles: List[ArticleEntry],
        defaults: DefaultVisibility,
        site_behavior: Dict[str, StageBehavior],
    ):
        self.articles = articles
        self.defaults = defaults
        self.site_behavior = site_behavior
        
        # Index by slug for quick lookup
        self._by_slug = {a.slug: a for a in articles}
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ContentManifest":
        """Load manifest from YAML file."""
        if path is None:
            path = cls._default_path()
        
        if not path.exists():
            logger.warning(f"Manifest not found at {path}, using defaults")
            return cls._empty()
        
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            
            return cls._from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load manifest: {e}")
            return cls._empty()
    
    @classmethod
    def _default_path(cls) -> Path:
        """Get default manifest path."""
        return Path(__file__).parent.parent.parent / "content" / "manifest.yaml"
    
    @classmethod
    def _empty(cls) -> "ContentManifest":
        """Create empty manifest with defaults."""
        return cls(
            articles=[],
            defaults=DefaultVisibility(),
            site_behavior={},
        )
    
    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "ContentManifest":
        """Parse manifest from dictionary."""
        articles = []
        for a in data.get("articles", []):
            vis_data = a.get("visibility", {})
            visibility = ArticleVisibility(
                min_stage=vis_data.get("min_stage", "FULL"),
                include_in_nav=vis_data.get("include_in_nav", False),
                pin_to_top=vis_data.get("pin_to_top", False),
            )
            
            meta_data = a.get("meta", {})
            meta = ArticleMeta(
                description=meta_data.get("description"),
                author=meta_data.get("author"),
                tags=meta_data.get("tags", []),
            )
            
            articles.append(ArticleEntry(
                slug=a["slug"],
                title=a.get("title", a["slug"]),
                visibility=visibility,
                meta=meta,
            ))
        
        defaults_data = data.get("defaults", {}).get("visibility", data.get("defaults", {}))
        defaults = DefaultVisibility(
            min_stage=defaults_data.get("min_stage", "FULL"),
            include_in_nav=defaults_data.get("include_in_nav", False),
            pin_to_top=defaults_data.get("pin_to_top", False),
        )
        
        # Auto-discover articles from content/articles/ directory
        known_slugs = {a.slug for a in articles}
        articles_dir = cls._default_path().parent / "articles"
        if articles_dir.exists():
            for json_file in sorted(articles_dir.glob("*.json")):
                slug = json_file.stem
                if slug not in known_slugs:
                    # Title from slug: "full_disclosure" -> "Full Disclosure"
                    title = slug.replace("_", " ").replace("-", " ").title()
                    articles.append(ArticleEntry(
                        slug=slug,
                        title=title,
                        visibility=ArticleVisibility(
                            min_stage=defaults.min_stage,
                            include_in_nav=True,
                            pin_to_top=False,
                        ),
                        meta=ArticleMeta(),
                    ))
                    logger.info(f"Auto-discovered article: {slug} (min_stage={defaults.min_stage})")
        
        site_behavior = {}
        for stage, behavior_data in data.get("stages", data.get("site_behavior", {})).items():
            site_behavior[stage] = StageBehavior(
                show_countdown=behavior_data.get("show_countdown", True),
                show_articles=behavior_data.get("show_articles", False),
                banner=behavior_data.get("banner"),
                banner_class=behavior_data.get("banner_class"),
            )
        
        return cls(articles, defaults, site_behavior)
    
    def get_article(self, slug: str) -> Optional[ArticleEntry]:
        """Get article entry by slug."""
        return self._by_slug.get(slug)
    
    def get_visible_articles(self, stage: str) -> List[ArticleEntry]:
        """Get all articles visible at the given stage."""
        visible = [a for a in self.articles if a.is_visible_at(stage)]
        
        # Sort: pinned first, then by title
        visible.sort(key=lambda a: (not a.visibility.pin_to_top, a.title))
        
        return visible
    
    def is_article_visible(self, slug: str, stage: str) -> bool:
        """Check if a specific article is visible at the stage."""
        article = self.get_article(slug)
        if article:
            return article.is_visible_at(stage)
        
        # Article not in manifest, use defaults
        default_order = STAGE_ORDER.get(self.defaults.min_stage, 50)
        current_order = STAGE_ORDER.get(stage, 0)
        return current_order >= default_order
    
    def get_stage_behavior(self, stage: str) -> StageBehavior:
        """Get site behavior for a stage."""
        return self.site_behavior.get(stage, StageBehavior())
    
    def get_nav_articles(self, stage: str) -> List[ArticleEntry]:
        """Get articles to show in navigation at given stage."""
        visible = self.get_visible_articles(stage)
        return [a for a in visible if a.visibility.include_in_nav]
