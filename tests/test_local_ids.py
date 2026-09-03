"""Tests for local ID prefix and sequence concurrency."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from vulndb.apps.core.models import SystemSettings
from vulndb.apps.vulns.models import LocalIdSequence


@pytest.mark.django_db
def test_validate_prefix_ok():
    assert SystemSettings.validate_prefix("acme") == "ACME"
    assert SystemSettings.validate_prefix("ORG12") == "ORG12"


@pytest.mark.django_db
def test_validate_prefix_reserved():
    with pytest.raises(ValidationError):
        SystemSettings.validate_prefix("CVE")
    with pytest.raises(ValidationError):
        SystemSettings.validate_prefix("BDU")
    with pytest.raises(ValidationError):
        SystemSettings.validate_prefix("A")
    with pytest.raises(ValidationError):
        SystemSettings.validate_prefix("bad-prefix")


@pytest.mark.django_db(transaction=True)
def test_local_id_sequence_next_id_format():
    SystemSettings.load()
    vid = LocalIdSequence.next_id("ACME")
    assert vid.startswith("ACME-")
    parts = vid.split("-")
    assert len(parts) == 3
    assert parts[2].isdigit() and len(parts[2]) == 4


@pytest.mark.django_db(transaction=True)
def test_local_id_sequence_concurrent():
    """Concurrent next_id must not produce duplicates (select_for_update + retry)."""
    year = timezone.localtime().year
    LocalIdSequence.objects.get_or_create(prefix="ACME", year=year, defaults={"last_number": 0})

    with connection.cursor() as cursor:
        cursor.execute("PRAGMA busy_timeout=10000")

    def _one(_):
        connection.close()
        connection.ensure_connection()
        with connection.cursor() as c:
            c.execute("PRAGMA busy_timeout=10000")
        return LocalIdSequence.next_id("ACME")

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(_one, range(9)))

    assert len(ids) == 9
    assert len(set(ids)) == 9
    assert all(i.startswith("ACME-") for i in ids)
    numbers = sorted(int(i.rsplit("-", 1)[1]) for i in ids)
    assert numbers == list(range(1, 10))
