from datetime import date
from uuid import uuid4

import pytest
from vantix_core.products import (
    ProductValidationError,
    canonicalise_product,
    canonicalise_products,
    select_effective_price,
)


def product() -> dict:
    return {
        "id": str(uuid4()),
        "product_definition_id": str(uuid4()),
        "item_code": "BAR-001",
        "item_name": "Barite",
        "packaging": "sack",
        "package_size": "025.000",
        "package_unit_code": "kg",
        "inventory_applicable": True,
        "inventory_unit_code": "package",
        "specific_gravity": "04.2000",
        "active": True,
        "prices": [
            {
                "id": str(uuid4()),
                "effective_from": "2026-01-01",
                "effective_to": "2026-07-01",
                "unit_price": "18.5000",
                "currency": "GBP",
                "price_basis_unit_code": "package",
            },
            {
                "id": str(uuid4()),
                "effective_from": "2026-07-01",
                "effective_to": None,
                "unit_price": "19.2500",
                "currency": "GBP",
                "price_basis_unit_code": "package",
            },
        ],
    }


def test_vtx_pro_001_product_units_sg_and_decimals_are_explicit_and_canonical() -> None:
    canonical = canonicalise_products([product()], "GBP")[0]
    assert canonical["package_size"] == "25"
    assert canonical["package_unit_code"] == "kg"
    assert canonical["inventory_unit_code"] == "package"
    assert canonical["specific_gravity"] == "4.2"
    assert canonical["prices"][0]["unit_price"] == "18.5"


def test_vtx_pro_002_effective_price_periods_are_half_open_and_non_overlapping() -> None:
    candidate = product()
    candidate["prices"][1]["effective_from"] = "2026-06-30"
    with pytest.raises(ProductValidationError) as overlap:
        canonicalise_product(candidate, "GBP")
    assert overlap.value.code == "PRICE_PERIOD_OVERLAP"


def test_vtx_pro_003_price_lookup_selects_the_boundary_date_without_ambiguity() -> None:
    prices = canonicalise_product(product(), "GBP")["prices"]
    selected = select_effective_price(prices, date(2026, 7, 1))
    assert selected is not None
    assert selected["unit_price"] == "19.25"


def test_vtx_pro_001_missing_sg_is_allowed_but_unit_dimension_mismatch_is_not() -> None:
    candidate = product()
    candidate.pop("specific_gravity")
    candidate["inventory_unit_code"] = "L"
    with pytest.raises(ProductValidationError) as mismatch:
        canonicalise_product(candidate, "GBP")
    assert mismatch.value.code == "INVENTORY_UNIT_DIMENSION_MISMATCH"

    candidate["inventory_unit_code"] = "package"
    canonical = canonicalise_product(candidate, "GBP")
    assert "specific_gravity" not in canonical


@pytest.mark.parametrize(
    ("package_unit", "price_basis"),
    [("kg", "t"), ("L", "L")],
)
def test_vtx_pro_001_package_inventory_accepts_content_compatible_pricing(
    package_unit: str, price_basis: str
) -> None:
    candidate = product()
    candidate["package_unit_code"] = package_unit
    candidate["inventory_unit_code"] = "package"
    for price in candidate["prices"]:
        price["price_basis_unit_code"] = price_basis
    canonical = canonicalise_product(candidate, "GBP")
    assert canonical["prices"][0]["price_basis_unit_code"] == price_basis


def test_vtx_pro_001_mass_product_rejects_volume_price_without_conversion_basis() -> None:
    candidate = product()
    candidate["inventory_unit_code"] = "package"
    candidate["prices"][0]["price_basis_unit_code"] = "L"
    with pytest.raises(ProductValidationError) as mismatch:
        canonicalise_product(candidate, "GBP")
    assert mismatch.value.code == "PRICE_BASIS_UNIT_MISMATCH"
