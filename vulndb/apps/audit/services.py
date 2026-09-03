"""Audit helpers."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType

from vulndb.apps.audit.models import AuditEntry


def log_action(user, action: str, target=None, meta: dict[str, Any] | None = None) -> AuditEntry:
    ct = None
    object_id = None
    target_repr = ""
    if target is not None:
        ct = ContentType.objects.get_for_model(target, for_concrete_model=False)
        object_id = getattr(target, "pk", None)
        target_repr = str(target)[:255]
    return AuditEntry.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        content_type=ct,
        object_id=object_id,
        target_repr=target_repr,
        meta=meta or {},
    )
