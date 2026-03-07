"""
Template Store — Memory of learned website layouts and components.
=================================================================
Stores extracted patterns from past sites so the LLM can reuse them.
File-backed JSON persistence.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Template data models
# ---------------------------------------------------------------------------

class StylePattern(BaseModel):
    """Extracted CSS/Tailwind style pattern."""
    name: str = ""
    description: str = ""
    css_classes: list[str] = Field(default_factory=list)
    color_scheme: dict[str, str] = Field(default_factory=dict)
    font_stack: str = ""
    spacing: str = ""            # compact, normal, spacious


class ComponentRecord(BaseModel):
    """A reusable page component extracted from a past site."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""               # e.g. "hero-centered", "pricing-3col"
    category: str = ""           # hero, nav, footer, cta, features, testimonials, etc.
    description: str = ""
    html_template: str = ""      # HTML with {{placeholders}}
    variables: list[str] = Field(default_factory=list)  # placeholder names
    business_types: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_url: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TemplateRecord(BaseModel):
    """A full site template learned from a past website."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    source_url: str = ""
    source_path: str = ""
    business_type: str = ""
    description: str = ""
    page_structure: list[dict[str, Any]] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    style: StylePattern = Field(default_factory=StylePattern)
    nav_pattern: str = ""        # top-bar, sidebar, hamburger
    footer_pattern: str = ""
    section_order: list[str] = Field(default_factory=list)  # common section order
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class TemplateStore:
    """
    Persistent store for learned templates and components.

    Storage layout:
        base_dir/
            templates.json      — list of TemplateRecord
            components.json     — list of ComponentRecord
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent / "memory" / "webgen_templates"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self._templates_path = self.base_dir / "templates.json"
        self._components_path = self.base_dir / "components.json"

        self._templates: list[TemplateRecord] = []
        self._components: list[ComponentRecord] = []
        self._load()

    # ── CRUD — Templates ─────────────────────────────────

    def add_template(self, template: TemplateRecord) -> str:
        """Add a template and return its ID."""
        self._templates.append(template)
        self._save()
        return template.id

    def get_template(self, template_id: str) -> Optional[TemplateRecord]:
        return next((t for t in self._templates if t.id == template_id), None)

    def list_templates(self, business_type: str = "") -> list[TemplateRecord]:
        if business_type:
            return [t for t in self._templates if t.business_type == business_type]
        return list(self._templates)

    def delete_template(self, template_id: str) -> bool:
        before = len(self._templates)
        self._templates = [t for t in self._templates if t.id != template_id]
        if len(self._templates) < before:
            self._save()
            return True
        return False

    # ── CRUD — Components ────────────────────────────────

    def add_component(self, component: ComponentRecord) -> str:
        """Add a component and return its ID."""
        self._components.append(component)
        self._save()
        return component.id

    def get_component(self, component_id: str) -> Optional[ComponentRecord]:
        return next((c for c in self._components if c.id == component_id), None)

    def list_components(self, category: str = "", business_type: str = "") -> list[ComponentRecord]:
        result = list(self._components)
        if category:
            result = [c for c in result if c.category == category]
        if business_type:
            result = [c for c in result if business_type in c.business_types]
        return result

    def find_components(self, categories: list[str], business_type: str = "") -> list[ComponentRecord]:
        """Find best-matching components for given categories."""
        result = []
        for cat in categories:
            matches = self.list_components(category=cat, business_type=business_type)
            if not matches:
                matches = self.list_components(category=cat)
            if matches:
                result.append(matches[0])  # Best match (first)
        return result

    def delete_component(self, component_id: str) -> bool:
        before = len(self._components)
        self._components = [c for c in self._components if c.id != component_id]
        if len(self._components) < before:
            self._save()
            return True
        return False

    # ── Persistence ──────────────────────────────────────

    def _load(self) -> None:
        if self._templates_path.exists():
            try:
                data = json.loads(self._templates_path.read_text())
                self._templates = [TemplateRecord(**t) for t in data]
            except Exception:
                self._templates = []

        if self._components_path.exists():
            try:
                data = json.loads(self._components_path.read_text())
                self._components = [ComponentRecord(**c) for c in data]
            except Exception:
                self._components = []

    def _save(self) -> None:
        self._templates_path.write_text(
            json.dumps([t.model_dump() for t in self._templates], indent=2)
        )
        self._components_path.write_text(
            json.dumps([c.model_dump() for c in self._components], indent=2)
        )

    @property
    def template_count(self) -> int:
        return len(self._templates)

    @property
    def component_count(self) -> int:
        return len(self._components)
