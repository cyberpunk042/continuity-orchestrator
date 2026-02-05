"""
Tests for the Content Manifest — Stage-based visibility.
"""

import pytest
from pathlib import Path
import tempfile
import yaml

from src.site.manifest import (
    ContentManifest,
    ArticleEntry,
    ArticleVisibility,
    ArticleMeta,
    DefaultVisibility,
    StageBehavior,
    STAGE_ORDER,
)


class TestStageOrder:
    """Tests for stage ordering."""
    
    def test_stage_order_values(self):
        """Test all stages have correct order."""
        assert STAGE_ORDER["OK"] < STAGE_ORDER["REMIND_1"]
        assert STAGE_ORDER["REMIND_1"] < STAGE_ORDER["REMIND_2"]
        assert STAGE_ORDER["REMIND_2"] < STAGE_ORDER["PRE_RELEASE"]
        assert STAGE_ORDER["PRE_RELEASE"] < STAGE_ORDER["PARTIAL"]
        assert STAGE_ORDER["PARTIAL"] < STAGE_ORDER["FULL"]
    
    def test_stage_order_completeness(self):
        """Test all expected stages are defined."""
        expected = ["OK", "REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL", "FULL"]
        for stage in expected:
            assert stage in STAGE_ORDER


class TestArticleVisibility:
    """Tests for ArticleVisibility."""
    
    def test_default_min_stage(self):
        """Test default min_stage is FULL."""
        vis = ArticleVisibility()
        assert vis.min_stage == "FULL"
    
    def test_min_stage_order_property(self):
        """Test min_stage_order returns correct value."""
        vis = ArticleVisibility(min_stage="PARTIAL")
        assert vis.min_stage_order == 40
    
    def test_unknown_stage_defaults_to_50(self):
        """Test unknown stage gets order 50."""
        vis = ArticleVisibility(min_stage="UNKNOWN")
        assert vis.min_stage_order == 50
    
    def test_default_nav_settings(self):
        """Test default navigation settings."""
        vis = ArticleVisibility()
        assert vis.include_in_nav is False
        assert vis.pin_to_top is False


class TestArticleEntry:
    """Tests for ArticleEntry."""
    
    def test_is_visible_at_same_stage(self):
        """Test article visible at its minimum stage."""
        entry = ArticleEntry(
            slug="test",
            title="Test",
            visibility=ArticleVisibility(min_stage="PARTIAL"),
        )
        assert entry.is_visible_at("PARTIAL") is True
    
    def test_is_visible_at_higher_stage(self):
        """Test article visible at higher stage."""
        entry = ArticleEntry(
            slug="test",
            title="Test",
            visibility=ArticleVisibility(min_stage="PARTIAL"),
        )
        assert entry.is_visible_at("FULL") is True
    
    def test_not_visible_at_lower_stage(self):
        """Test article not visible at lower stage."""
        entry = ArticleEntry(
            slug="test",
            title="Test",
            visibility=ArticleVisibility(min_stage="PARTIAL"),
        )
        assert entry.is_visible_at("PRE_RELEASE") is False
        assert entry.is_visible_at("REMIND_1") is False
        assert entry.is_visible_at("OK") is False
    
    def test_ok_article_always_visible(self):
        """Test OK-level article visible at all stages."""
        entry = ArticleEntry(
            slug="about",
            title="About",
            visibility=ArticleVisibility(min_stage="OK"),
        )
        for stage in STAGE_ORDER.keys():
            assert entry.is_visible_at(stage) is True


class TestContentManifest:
    """Tests for ContentManifest."""
    
    @pytest.fixture
    def sample_manifest(self):
        """Create a sample manifest."""
        articles = [
            ArticleEntry(
                slug="about",
                title="About",
                visibility=ArticleVisibility(min_stage="OK", include_in_nav=True),
            ),
            ArticleEntry(
                slug="notice",
                title="Notice",
                visibility=ArticleVisibility(min_stage="PARTIAL", include_in_nav=True),
            ),
            ArticleEntry(
                slug="disclosure",
                title="Full Disclosure",
                visibility=ArticleVisibility(min_stage="FULL", pin_to_top=True),
            ),
        ]
        return ContentManifest(
            articles=articles,
            defaults=DefaultVisibility(),
            site_behavior={
                "OK": StageBehavior(show_countdown=True, show_articles=False),
                "FULL": StageBehavior(show_countdown=True, show_articles=True),
            },
        )
    
    def test_get_article_by_slug(self, sample_manifest):
        """Test getting article by slug."""
        article = sample_manifest.get_article("about")
        assert article is not None
        assert article.title == "About"
    
    def test_get_article_not_found(self, sample_manifest):
        """Test getting non-existent article returns None."""
        assert sample_manifest.get_article("nonexistent") is None
    
    def test_get_visible_articles_ok(self, sample_manifest):
        """Test visible articles at OK stage."""
        visible = sample_manifest.get_visible_articles("OK")
        assert len(visible) == 1
        assert visible[0].slug == "about"
    
    def test_get_visible_articles_partial(self, sample_manifest):
        """Test visible articles at PARTIAL stage."""
        visible = sample_manifest.get_visible_articles("PARTIAL")
        assert len(visible) == 2
        slugs = [a.slug for a in visible]
        assert "about" in slugs
        assert "notice" in slugs
    
    def test_get_visible_articles_full(self, sample_manifest):
        """Test visible articles at FULL stage."""
        visible = sample_manifest.get_visible_articles("FULL")
        assert len(visible) == 3
    
    def test_visible_articles_pinned_first(self, sample_manifest):
        """Test pinned articles appear first."""
        visible = sample_manifest.get_visible_articles("FULL")
        assert visible[0].slug == "disclosure"  # Pinned
        assert visible[0].visibility.pin_to_top is True
    
    def test_is_article_visible(self, sample_manifest):
        """Test is_article_visible method."""
        assert sample_manifest.is_article_visible("about", "OK") is True
        assert sample_manifest.is_article_visible("notice", "OK") is False
        assert sample_manifest.is_article_visible("notice", "PARTIAL") is True
    
    def test_is_article_visible_unknown_uses_defaults(self, sample_manifest):
        """Test unknown article uses default visibility."""
        # Default min_stage is FULL
        assert sample_manifest.is_article_visible("unknown", "PARTIAL") is False
        assert sample_manifest.is_article_visible("unknown", "FULL") is True
    
    def test_get_stage_behavior(self, sample_manifest):
        """Test getting stage behavior."""
        ok_behavior = sample_manifest.get_stage_behavior("OK")
        assert ok_behavior.show_countdown is True
        assert ok_behavior.show_articles is False
        
        full_behavior = sample_manifest.get_stage_behavior("FULL")
        assert full_behavior.show_articles is True
    
    def test_get_stage_behavior_unknown_returns_default(self, sample_manifest):
        """Test unknown stage returns default behavior."""
        behavior = sample_manifest.get_stage_behavior("UNKNOWN")
        assert behavior.show_countdown is True  # Default
    
    def test_get_nav_articles(self, sample_manifest):
        """Test getting navigation articles."""
        nav = sample_manifest.get_nav_articles("PARTIAL")
        assert len(nav) == 2
        
        # Disclosure is not in nav (only pinned)
        nav_full = sample_manifest.get_nav_articles("FULL")
        slugs = [a.slug for a in nav_full]
        assert "disclosure" not in slugs
    
    def test_empty_manifest(self):
        """Test empty manifest creation."""
        manifest = ContentManifest._empty()
        assert manifest.articles == []
        assert manifest.defaults.min_stage == "FULL"


class TestManifestLoading:
    """Tests for manifest file loading."""
    
    def test_load_from_yaml(self):
        """Test loading manifest from YAML file."""
        manifest_data = {
            "articles": [
                {
                    "slug": "welcome",
                    "title": "Welcome",
                    "visibility": {
                        "min_stage": "OK",
                        "include_in_nav": True,
                    },
                },
                {
                    "slug": "secret",
                    "title": "Secret Info",
                    "visibility": {
                        "min_stage": "FULL",
                        "pin_to_top": True,
                    },
                    "meta": {
                        "description": "Top secret",
                        "author": "Admin",
                        "tags": ["secret", "important"],
                    },
                },
            ],
            "defaults": {
                "min_stage": "PARTIAL",
            },
            "site_behavior": {
                "FULL": {
                    "show_articles": True,
                    "banner": "⚠️ Full disclosure active",
                    "banner_class": "banner-critical",
                },
            },
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(manifest_data, f)
            path = Path(f.name)
        
        try:
            manifest = ContentManifest.load(path)
            
            assert len(manifest.articles) == 2
            assert manifest.get_article("welcome").title == "Welcome"
            assert manifest.get_article("secret").visibility.pin_to_top is True
            assert manifest.get_article("secret").meta.author == "Admin"
            assert manifest.defaults.min_stage == "PARTIAL"
            
            full_behavior = manifest.get_stage_behavior("FULL")
            assert full_behavior.show_articles is True
            assert "Full disclosure" in full_behavior.banner
        finally:
            path.unlink()
    
    def test_load_missing_file_returns_empty(self):
        """Test loading missing file returns empty manifest."""
        manifest = ContentManifest.load(Path("/nonexistent/path.yaml"))
        assert len(manifest.articles) == 0
    
    def test_load_minimal_article(self):
        """Test loading article with minimal fields."""
        manifest_data = {
            "articles": [
                {"slug": "minimal"},
            ],
        }
        
        manifest = ContentManifest._from_dict(manifest_data)
        
        article = manifest.get_article("minimal")
        assert article is not None
        assert article.title == "minimal"  # Uses slug as title
        assert article.visibility.min_stage == "FULL"  # Default
