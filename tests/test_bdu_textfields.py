"""BDU TextField parsing — no varchar(255) truncation."""

from io import BytesIO

import pytest
from openpyxl import Workbook

from vulndb.apps.vulns.models import Vulnerability
from vulndb.apps.vulns.tasks import _parse_bdu_row, sync_bdu


@pytest.mark.django_db
def test_vendor_product_are_textfields():
    field_vendor = Vulnerability._meta.get_field("vendor")
    field_product = Vulnerability._meta.get_field("product_name")
    field_version = Vulnerability._meta.get_field("product_version")
    assert field_vendor.get_internal_type() == "TextField"
    assert field_product.get_internal_type() == "TextField"
    assert field_version.get_internal_type() == "TextField"
    # No max_length clipping
    assert getattr(field_vendor, "max_length", None) is None
    assert getattr(field_product, "max_length", None) is None


@pytest.mark.django_db
def test_parse_bdu_long_strings_and_persist(monkeypatch, settings):
    long_vendor = "V" * 500
    long_product = "P" * 800
    long_version = "Ver " + ("1.2.3-build-" * 40)

    wb = Workbook()
    ws = wb.active
    ws.append(["hdr1"])
    ws.append(["hdr2"])
    ws.append(
        [
            "Идентификатор",
            "Название",
            "Описание",
            "Вендор",
            "Продукт",
            "Версия",
            "x",
            "refs",
            "y",
            "fix",
        ]
    )
    ws.append(
        [
            "2024-00001",
            "Long title",
            "Description",
            long_vendor,
            long_product,
            long_version,
            "",
            "",
            "",
            "patch me",
        ]
    )
    buf = BytesIO()
    wb.save(buf)
    content = buf.getvalue()

    class FakeResp:
        status_code = 200

        def __init__(self, body: bytes):
            self.content = body

        def raise_for_status(self):
            return None

    from vulndb.apps.core.models import SystemSettings

    s = SystemSettings.load()
    s.bdu_enabled = True
    s.bdu_verify_ssl = False
    s.save()

    monkeypatch.setattr(
        "vulndb.apps.vulns.tasks.request_with_retries",
        lambda *a, **k: FakeResp(content),
    )

    result = sync_bdu()
    assert result["ok"] is True
    obj = Vulnerability.objects.get(vuln_id="BDU:2024-00001")
    assert obj.vendor == long_vendor
    assert obj.product_name == long_product
    assert obj.product_version == long_version
    assert len(obj.vendor) == 500
    assert len(obj.product_name) == 800


def test_parse_bdu_row_positions():
    cells = ["2024-1", "t", "d", "vendor", "product", "1.0", "", "CVE-2024-1111", "", "fix"]
    parsed = _parse_bdu_row(cells)
    assert parsed["bdu_id"] == "2024-1"
    assert parsed["vendor"] == "vendor"
    assert "CVE-2024-1111" in parsed["other_ids"]
