"""Pure product, packaging, unit, and effective-price rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

UNIT_DIMENSIONS = {
    "kg": "mass",
    "t": "mass",
    "lb": "mass",
    "L": "volume",
    "m3": "volume",
    "gal_us": "volume",
    "bbl": "volume",
    "each": "count",
    "package": "package",
}
PACKAGE_CONTENT_UNITS = frozenset(UNIT_DIMENSIONS) - {"package"}
INVENTORY_UNITS = frozenset(UNIT_DIMENSIONS)
PACKAGING_TYPES = frozenset({"sack", "pail", "drum", "tote", "bulk", "case", "each", "other"})


class ProductValidationError(ValueError):
    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def canonical_decimal(value: object, *, code: str, field: str, allow_zero: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductValidationError(code, field, "A decimal string is required.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProductValidationError(code, field, "A finite decimal string is required.") from exc
    if not parsed.is_finite() or parsed < 0 or (not allow_zero and parsed == 0):
        qualifier = "non-negative" if allow_zero else "greater than zero"
        raise ProductValidationError(code, field, f"Value must be finite and {qualifier}.")
    return "0" if parsed == 0 else format(parsed.normalize(), "f")


def _uuid(value: object, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProductValidationError("PRODUCT_ID_INVALID", field, "A UUID is required.") from exc


def _date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ProductValidationError("PRICE_DATE_INVALID", field, "Use an ISO date.") from exc


def canonicalise_product(
    product: Mapping[str, Any], project_currency: str, *, require_price: bool = True
) -> dict[str, Any]:
    result = deepcopy(dict(product))
    result["id"] = _uuid(product.get("id"), "id")
    for field in ("item_code", "item_name"):
        value = product.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProductValidationError("PRODUCT_FIELD_REQUIRED", field, f"{field} is required.")
        result[field] = value.strip()

    packaging = product.get("packaging")
    if packaging not in PACKAGING_TYPES:
        raise ProductValidationError(
            "PACKAGING_UNRECOGNISED", "packaging", "Select a controlled packaging type."
        )
    package_unit = product.get("package_unit_code")
    if package_unit not in PACKAGE_CONTENT_UNITS:
        raise ProductValidationError(
            "PACKAGE_UNIT_UNRECOGNISED",
            "package_unit_code",
            "Select a supported mass, volume, or count unit.",
        )
    result["package_size"] = canonical_decimal(
        product.get("package_size"),
        code="PACKAGE_SIZE_INVALID",
        field="package_size",
        allow_zero=False,
    )

    inventory_applicable = product.get("inventory_applicable")
    if not isinstance(inventory_applicable, bool):
        raise ProductValidationError(
            "INVENTORY_APPLICABILITY_REQUIRED",
            "inventory_applicable",
            "Inventory applicability must be explicit.",
        )
    inventory_unit = product.get("inventory_unit_code")
    if inventory_applicable:
        if inventory_unit not in INVENTORY_UNITS:
            raise ProductValidationError(
                "INVENTORY_UNIT_REQUIRED",
                "inventory_unit_code",
                "Inventory items require a supported inventory unit.",
            )
        if inventory_unit != "package" and (
            UNIT_DIMENSIONS[str(inventory_unit)] != UNIT_DIMENSIONS[str(package_unit)]
        ):
            raise ProductValidationError(
                "INVENTORY_UNIT_DIMENSION_MISMATCH",
                "inventory_unit_code",
                "Inventory and package-content units must be dimensionally compatible.",
            )
    elif inventory_unit is not None:
        raise ProductValidationError(
            "INVENTORY_UNIT_NOT_APPLICABLE",
            "inventory_unit_code",
            "A non-inventory product cannot define an inventory unit.",
        )

    specific_gravity = product.get("specific_gravity")
    if specific_gravity is not None:
        result["specific_gravity"] = canonical_decimal(
            specific_gravity,
            code="SPECIFIC_GRAVITY_INVALID",
            field="specific_gravity",
            allow_zero=False,
        )

    prices = product.get("prices")
    if not isinstance(prices, Sequence) or isinstance(prices, (str, bytes)):
        raise ProductValidationError("PRICE_LIST_INVALID", "prices", "Prices must be a list.")
    canonical_prices = [
        canonicalise_price(price, product=result, project_currency=project_currency)
        for price in prices
        if isinstance(price, Mapping)
    ]
    if len(canonical_prices) != len(prices):
        raise ProductValidationError("PRICE_INVALID", "prices", "Each price must be an object.")
    canonical_prices.sort(key=lambda item: (item["effective_from"], item["id"]))
    _reject_overlaps(canonical_prices)
    if require_price and result.get("active", True) and not canonical_prices:
        raise ProductValidationError(
            "ACTIVE_PRODUCT_PRICE_REQUIRED",
            "prices",
            "Each active product requires at least one effective price.",
        )
    result["prices"] = canonical_prices
    return result


def canonicalise_price(
    price: Mapping[str, Any], *, product: Mapping[str, Any], project_currency: str
) -> dict[str, Any]:
    result = deepcopy(dict(price))
    result["id"] = _uuid(price.get("id"), "prices.id")
    effective_from = _date(price.get("effective_from"), "prices.effective_from")
    raw_to = price.get("effective_to")
    effective_to = _date(raw_to, "prices.effective_to") if raw_to is not None else None
    if effective_to is not None and effective_to <= effective_from:
        raise ProductValidationError(
            "PRICE_RANGE_INVALID",
            "prices.effective_to",
            "Effective-to is exclusive and must be after effective-from.",
        )
    result["effective_from"] = effective_from.isoformat()
    result["effective_to"] = effective_to.isoformat() if effective_to else None
    result["unit_price"] = canonical_decimal(
        price.get("unit_price"),
        code="PRICE_AMOUNT_INVALID",
        field="prices.unit_price",
        allow_zero=True,
    )
    currency = price.get("currency")
    if currency != project_currency:
        raise ProductValidationError(
            "PRICE_CURRENCY_MISMATCH",
            "prices.currency",
            "Price currency must match the project currency.",
        )
    basis = price.get("price_basis_unit_code")
    inventory_unit = product.get("inventory_unit_code")
    package_unit = str(product["package_unit_code"])
    allowed_basis = {"package"}
    if inventory_unit and inventory_unit != "package":
        dimension = UNIT_DIMENSIONS[str(inventory_unit)]
        allowed_basis.update(
            unit
            for unit, candidate_dimension in UNIT_DIMENSIONS.items()
            if candidate_dimension == dimension
        )
    elif inventory_unit == "package":
        allowed_basis.add("package")
    else:
        dimension = UNIT_DIMENSIONS[package_unit]
        allowed_basis.update(
            unit
            for unit, candidate_dimension in UNIT_DIMENSIONS.items()
            if candidate_dimension == dimension
        )
    if basis not in allowed_basis:
        raise ProductValidationError(
            "PRICE_BASIS_UNIT_MISMATCH",
            "prices.price_basis_unit_code",
            "Price basis must be per package or dimensionally compatible with the product.",
        )
    return result


def _reject_overlaps(prices: Sequence[Mapping[str, Any]]) -> None:
    previous_end: date | None = None
    for index, price in enumerate(prices):
        start = _date(price["effective_from"], f"prices.{index}.effective_from")
        end = (
            _date(price["effective_to"], f"prices.{index}.effective_to")
            if price.get("effective_to") is not None
            else None
        )
        if index and (previous_end is None or start < previous_end):
            raise ProductValidationError(
                "PRICE_PERIOD_OVERLAP",
                f"prices.{index}.effective_from",
                "Effective price periods cannot overlap.",
            )
        previous_end = end


def canonicalise_products(
    products: Sequence[Mapping[str, Any]], project_currency: str
) -> list[dict[str, Any]]:
    canonical = [canonicalise_product(product, project_currency) for product in products]
    active = [product for product in canonical if product.get("active", True)]
    if not active:
        raise ProductValidationError(
            "ACTIVE_PRODUCT_REQUIRED", "products", "At least one active product is required."
        )
    codes = [str(product["item_code"]).casefold() for product in canonical]
    if len(codes) != len(set(codes)):
        raise ProductValidationError(
            "DUPLICATE_PRODUCT_CODE", "products", "Product item codes must be unique."
        )
    return sorted(canonical, key=lambda item: (str(item["item_code"]).casefold(), item["id"]))


def select_effective_price(
    prices: Sequence[Mapping[str, Any]], at_date: date
) -> Mapping[str, Any] | None:
    for price in prices:
        start = _date(price.get("effective_from"), "effective_from")
        raw_end = price.get("effective_to")
        end = _date(raw_end, "effective_to") if raw_end is not None else None
        if start <= at_date and (end is None or at_date < end):
            return price
    return None
