from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ServiceType(str, Enum):
    WEBSITE = "website"
    SEO = "seo"
    AI_RECEPTIONIST = "ai_receptionist"
    SOCIAL_MEDIA = "social_media"


class ServiceStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class CustomerService(BaseModel):
    id: str
    type: ServiceType
    status: ServiceStatus = ServiceStatus.PENDING
    progress_percent: int = 0
    assigned_agents: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class Customer(BaseModel):
    id: str
    name: str
    email: str
    business_name: str
    tier: str = Field(default="foundation", pattern="^(foundation|growth|domination)$")
    website_url: str | None = None
    social_media_accounts: dict[str, str] = Field(default_factory=dict)
    monthly_token_budget: int = 100000
    tokens_used_this_month: int = 0
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    services: list[CustomerService] = Field(default_factory=lambda: [])


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=5, max_length=254)
    business_name: str = Field(..., min_length=1, max_length=150)
    tier: str = Field(default="foundation", pattern="^(foundation|growth|domination)$")

    # Inline email-format validation (no extra dependency required)
    _EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
    # Characters that must not appear in name / business_name fields
    _HTML_CHARS = frozenset("<>\"';&|")

    @field_validator("name", "business_name", mode="before")
    @classmethod
    def strip_and_block_html(cls, v: str) -> str:
        v = v.strip()
        bad = cls._HTML_CHARS & set(v)
        if bad:
            raise ValueError(f"Field contains disallowed characters: {', '.join(sorted(bad))}")
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalise_and_validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not cls._EMAIL_RE.fullmatch(v):
            raise ValueError("Invalid email address format")
        return v


class AddServiceRequest(BaseModel):
    service_type: ServiceType
    notes: str = ""
