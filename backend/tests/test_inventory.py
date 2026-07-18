from decimal import Decimal

import pytest
from vantix_core.inventory import (
    InventoryValidationError,
    build_opening_line,
    build_reversal_line,
    calculate_posted_amount,
    convert_opening_quantity,
)


def test_vtx_pro_005_packages_convert_to_positive_canonical_content() -> None:
    quantity, unit = convert_opening_quantity(
        "4", "package", package_size="25", package_unit_code="kg"
    )
    assert quantity == "100"
    assert unit == "kg"


def test_vtx_unit_002_canonical_quantity_rounds_half_up_to_ledger_scale() -> None:
    quantity, unit = convert_opening_quantity(
        "1.000000000001", "lb", package_size="25", package_unit_code="kg"
    )
    assert quantity == "0.45359237"
    assert Decimal(quantity) == Decimal("0.453592370000")
    assert unit == "kg"


def test_vtx_unit_002_content_units_must_match_package_dimension() -> None:
    with pytest.raises(InventoryValidationError) as mismatch:
        convert_opening_quantity("5", "L", package_size="25", package_unit_code="kg")
    assert mismatch.value.code == "INVENTORY_UNIT_DIMENSION_MISMATCH"


def test_vtx_cst_001_002_package_and_content_prices_round_half_up() -> None:
    assert (
        calculate_posted_amount(
            "100",
            price_basis_unit_code="package",
            unit_price="18.555",
            package_size="25",
            package_unit_code="kg",
            currency="GBP",
        )
        == "74.22"
    )
    assert (
        calculate_posted_amount(
            "100",
            price_basis_unit_code="t",
            unit_price="900",
            package_size="25",
            package_unit_code="kg",
            currency="GBP",
        )
        == "90.00"
    )
    assert (
        calculate_posted_amount(
            "1",
            price_basis_unit_code="each",
            unit_price="18.5",
            package_size="1",
            package_unit_code="each",
            currency="JPY",
        )
        == "19"
    )


def test_vtx_rec_014_missing_price_stays_unavailable_not_zero() -> None:
    line = build_opening_line(
        entered_quantity="2",
        entered_unit_code="package",
        product={"package_size": "25", "package_unit_code": "kg"},
        price=None,
    )
    assert line["price_status"] == "unavailable"
    assert line["applied_unit_price"] is None
    assert line["posted_line_amount"] is None


def test_vtx_rec_004_015_reversal_is_exact_opposite_without_repricing() -> None:
    original = build_opening_line(
        entered_quantity="4",
        entered_unit_code="package",
        product={"package_size": "25", "package_unit_code": "kg"},
        price={
            "id": "00000000-0000-4000-8000-000000000001",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "unit_price": "18.5",
            "price_basis_unit_code": "package",
            "currency": "GBP",
        },
    )
    reversal = build_reversal_line(original)
    assert Decimal(reversal["entered_quantity"]) == -Decimal(original["entered_quantity"])
    assert Decimal(reversal["canonical_signed_quantity"]) == -Decimal(
        original["canonical_signed_quantity"]
    )
    assert Decimal(reversal["posted_line_amount"]) == -Decimal(original["posted_line_amount"])
    assert reversal["product_price_version_id"] == original["product_price_version_id"]
