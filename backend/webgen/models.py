"""
WebGen Models — Data structures for the web generation pipeline.
================================================================
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BusinessType(str, Enum):
    """Common business verticals with known layout patterns."""
    RESTAURANT = "restaurant"
    ECOMMERCE = "ecommerce"
    SAAS = "saas"
    AGENCY = "agency"
    PORTFOLIO = "portfolio"
    MEDICAL = "medical"
    LEGAL = "legal"
    REALESTATE = "realestate"
    FITNESS = "fitness"
    EDUCATION = "education"
    NONPROFIT = "nonprofit"
    CONSTRUCTION = "construction"
    SALON = "salon"
    AUTOMOTIVE = "automotive"
    CUSTOM = "custom"


class SiteStatus(str, Enum):
    """State machine for site generation."""
    BRIEF = "brief"              # Client brief captured
    PLANNED = "planned"          # Sitemap + pages planned
    GENERATING = "generating"    # Pages being generated
    GENERATED = "generated"      # All pages generated
    SEO_PASS = "seo_pass"        # SEO optimization done
    AEO_PASS = "aeo_pass"        # AEO optimization done
    QA_PASS = "qa_pass"          # Quality assurance passed
    READY = "ready"              # Ready for client review
    CUSTOMIZING = "customizing"  # Client customization in progress
    DEPLOYED = "deployed"        # Site deployed


# Valid state transitions
SITE_TRANSITIONS: dict[SiteStatus, list[SiteStatus]] = {
    SiteStatus.BRIEF: [SiteStatus.PLANNED],
    SiteStatus.PLANNED: [SiteStatus.GENERATING],
    SiteStatus.GENERATING: [SiteStatus.GENERATED, SiteStatus.PLANNED],
    SiteStatus.GENERATED: [SiteStatus.SEO_PASS],
    SiteStatus.SEO_PASS: [SiteStatus.AEO_PASS],
    SiteStatus.AEO_PASS: [SiteStatus.QA_PASS, SiteStatus.GENERATED],
    SiteStatus.QA_PASS: [SiteStatus.READY, SiteStatus.GENERATED],
    SiteStatus.READY: [SiteStatus.CUSTOMIZING, SiteStatus.DEPLOYED],
    SiteStatus.CUSTOMIZING: [SiteStatus.QA_PASS, SiteStatus.DEPLOYED],
    SiteStatus.DEPLOYED: [],
}


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class SEOProfile(BaseModel):
    """SEO configuration for a page."""
    title: str = ""
    meta_description: str = ""
    keywords: list[str] = Field(default_factory=list)
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    canonical_url: str = ""
    schema_type: str = ""          # e.g. "LocalBusiness", "Product"
    schema_json_ld: dict = Field(default_factory=dict)


class AEOProfile(BaseModel):
    """Answer-Engine Optimization profile."""
    faq_pairs: list[dict[str, str]] = Field(default_factory=list)  # [{q, a}]
    speakable_selectors: list[str] = Field(default_factory=list)
    entity_name: str = ""
    entity_type: str = ""
    entity_description: str = ""
    topic_cluster: str = ""
    related_topics: list[str] = Field(default_factory=list)


class SectionSpec(BaseModel):
    """Specification for a page section."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""                 # e.g. "hero", "features", "cta"
    component_type: str = ""       # e.g. "hero-centered", "grid-3col"
    content: dict[str, Any] = Field(default_factory=dict)
    html: str = ""                 # Generated HTML
    order: int = 0


class PageSpec(BaseModel):
    """Specification for a single page."""
    slug: str = ""                 # e.g. "index", "about", "services"
    title: str = ""
    purpose: str = ""
    sections: list[SectionSpec] = Field(default_factory=list)
    seo: SEOProfile = Field(default_factory=SEOProfile)
    aeo: AEOProfile = Field(default_factory=AEOProfile)
    html: str = ""                 # Final assembled HTML
    nav_label: str = ""            # Label in navigation
    nav_order: int = 0


class ClientBrief(BaseModel):
    """Information gathered from the client."""
    business_name: str = ""
    business_type: BusinessType = BusinessType.CUSTOM
    tagline: str = ""
    description: str = ""
    services: list[str] = Field(default_factory=list)
    target_audience: str = ""
    tone: str = "professional"     # professional, friendly, bold, minimal
    colors: dict[str, str] = Field(default_factory=dict)  # primary, secondary, accent
    logo_url: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    social_links: dict[str, str] = Field(default_factory=dict)
    competitors: list[str] = Field(default_factory=list)
    special_features: list[str] = Field(default_factory=list)
    pages_requested: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Main project model
# ---------------------------------------------------------------------------

class SiteProject(BaseModel):
    """Top-level project for a website generation job."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    status: SiteStatus = SiteStatus.BRIEF
    brief: ClientBrief = Field(default_factory=ClientBrief)
    pages: list[PageSpec] = Field(default_factory=list)
    template_ids: list[str] = Field(default_factory=list)  # which templates influenced
    output_dir: str = ""           # where generated files are written
    global_css: str = ""           # shared styles
    sitemap_xml: str = ""
    robots_txt: str = ""
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def advance(self, new_status: SiteStatus) -> None:
        """Transition to a new status with validation."""
        allowed = SITE_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition from {self.status.value} to {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        self.status = new_status
        self.updated_at = datetime.utcnow().isoformat()
