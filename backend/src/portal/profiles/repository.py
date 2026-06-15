"""Profile repository and utilities."""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    # Convert to lowercase and remove non-alphanumeric except spaces and hyphens
    slug = re.sub(r"[^a-z0-9\s\-]", "", text.lower())
    # Replace spaces with hyphens and collapse multiple hyphens
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    # Return empty fallback if result is empty
    return slug.strip("-") or "profil"


class ProfileError(Exception):
    """Base exception for profile operations."""
    pass


class ProfileRepository:
    """Repository for managing profiles."""
    pass
