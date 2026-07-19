"""Pure append-only inventory quantity, price, and reversal rules."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any
from unicodedata import normalize

UNIT_DIMENSIONS = {
    "kg": "mass",
    "t": "mass",
    "lb": "mass",
    "L": "volume",
    "m3": "volume",
    "gal_us": "volume",
    "bbl": "volume",
    "each": "count",
}
CANONICAL_UNITS = {"mass": "kg", "volume": "L", "count": "each"}
UNIT_TO_CANONICAL = {
    "kg": Decimal("1"),
    "t": Decimal("1000"),
    "lb": Decimal("0.45359237"),
    "L": Decimal("1"),
    "m3": Decimal("1000"),
    "gal_us": Decimal("3.785411784"),
    "bbl": Decimal("158.987294928"),
    "each": Decimal("1"),
}
CURRENCY_MINOR_UNITS = {
    "BIF": 0,
    "CLF": 4,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "UYW": 4,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
}
CANONICAL_QUANTITY_SCALE = 12
CANONICAL_QUANTITY_QUANTUM = Decimal(1).scaleb(-CANONICAL_QUANTITY_SCALE)


class InventoryValidationError(ValueError):
    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _decimal(value: object, *, code: str, field: str, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise InventoryValidationError(code, field, "A decimal string is required.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise InventoryValidationError(code, field, "A finite decimal string is required.") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        qualifier = "greater than zero" if positive else "finite"
        raise InventoryValidationError(code, field, f"Value must be {qualifier}.")
    return parsed


def decimal_string(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def currency_minor_unit_scale(currency: str) -> int:
    return CURRENCY_MINOR_UNITS.get(currency, 2)


def money_string(value: Decimal, scale: int) -> str:
    return format(value, f".{scale}f")


def normalise_receipt_reference(value: str, *, field: str) -> tuple[str, str]:
    stored = " ".join(normalize("NFC", value).strip().split())
    if not stored:
        raise InventoryValidationError(
            "RECEIPT_REFERENCE_REQUIRED", field, "A non-empty receipt reference is required."
        )
    return stored, stored.lower()


def canonical_quantity(value: Decimal) -> Decimal:
    """Round a canonical ledger quantity to its persisted 12-decimal authority."""

    with localcontext() as context:
        context.prec = max(38, len(value.as_tuple().digits) + CANONICAL_QUANTITY_SCALE)
        rounded = value.quantize(CANONICAL_QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)
    if rounded <= 0:
        raise InventoryValidationError(
            "INVENTORY_QUANTITY_BELOW_PRECISION",
            "entered_quantity",
            "Quantity is below canonical ledger precision.",
        )
    return rounded


def convert_opening_quantity(
    entered_quantity: str,
    entered_unit_code: str,
    *,
    package_size: str,
    package_unit_code: str,
) -> tuple[str, str]:
    """Return positive canonical quantity and unit for one opening line."""

    quantity = _decimal(
        entered_quantity,
        code="INVENTORY_QUANTITY_INVALID",
        field="entered_quantity",
        positive=True,
    )
    package_quantity = _decimal(
        package_size,
        code="PACKAGE_SIZE_INVALID",
        field="package_size",
        positive=True,
    )
    if package_unit_code not in UNIT_DIMENSIONS:
        raise InventoryValidationError(
            "PACKAGE_UNIT_UNRECOGNISED", "package_unit_code", "Package unit is unsupported."
        )
    package_dimension = UNIT_DIMENSIONS[package_unit_code]
    if entered_unit_code == "package":
        canonical = quantity * package_quantity * UNIT_TO_CANONICAL[package_unit_code]
    else:
        if entered_unit_code not in UNIT_DIMENSIONS:
            raise InventoryValidationError(
                "INVENTORY_UNIT_UNRECOGNISED",
                "entered_unit_code",
                "Entered unit is unsupported.",
            )
        if UNIT_DIMENSIONS[entered_unit_code] != package_dimension:
            raise InventoryValidationError(
                "INVENTORY_UNIT_DIMENSION_MISMATCH",
                "entered_unit_code",
                "Entered unit must match the package-content dimension.",
            )
        canonical = quantity * UNIT_TO_CANONICAL[entered_unit_code]
    canonical = canonical_quantity(canonical)
    return decimal_string(canonical), CANONICAL_UNITS[package_dimension]


def calculate_package_count(
    canonical_quantity: str, *, package_size: str, package_unit_code: str
) -> str:
    canonical = _decimal(
        canonical_quantity,
        code="CANONICAL_QUANTITY_INVALID",
        field="canonical_quantity",
        positive=True,
    )
    package_quantity = _decimal(
        package_size,
        code="PACKAGE_SIZE_INVALID",
        field="package_size",
        positive=True,
    )
    factor = UNIT_TO_CANONICAL.get(package_unit_code)
    if factor is None:
        raise InventoryValidationError(
            "PACKAGE_UNIT_UNRECOGNISED", "package_unit_code", "Package unit is unsupported."
        )
    return decimal_string(canonical / (package_quantity * factor))


def calculate_posted_amount(
    canonical_quantity: str,
    *,
    price_basis_unit_code: str,
    unit_price: str,
    package_size: str,
    package_unit_code: str,
    currency: str,
) -> str:
    """Calculate and currency-round one frozen posted line amount."""

    canonical = _decimal(
        canonical_quantity,
        code="CANONICAL_QUANTITY_INVALID",
        field="canonical_quantity",
        positive=True,
    )
    price = _decimal(unit_price, code="PRICE_AMOUNT_INVALID", field="unit_price")
    package_quantity = _decimal(
        package_size,
        code="PACKAGE_SIZE_INVALID",
        field="package_size",
        positive=True,
    )
    package_dimension = UNIT_DIMENSIONS.get(package_unit_code)
    if package_dimension is None:
        raise InventoryValidationError(
            "PACKAGE_UNIT_UNRECOGNISED", "package_unit_code", "Package unit is unsupported."
        )
    if price_basis_unit_code == "package":
        canonical_per_package = package_quantity * UNIT_TO_CANONICAL[package_unit_code]
        basis_quantity = canonical / canonical_per_package
    else:
        basis_dimension = UNIT_DIMENSIONS.get(price_basis_unit_code)
        if basis_dimension != package_dimension:
            raise InventoryValidationError(
                "PRICE_BASIS_UNIT_MISMATCH",
                "price_basis_unit_code",
                "Price basis must match package content or be per package.",
            )
        basis_quantity = canonical / UNIT_TO_CANONICAL[price_basis_unit_code]
    scale = currency_minor_unit_scale(currency)
    quantum = Decimal(1).scaleb(-scale)
    return format((basis_quantity * price).quantize(quantum, rounding=ROUND_HALF_UP), f".{scale}f")


def build_opening_line(
    *,
    entered_quantity: str,
    entered_unit_code: str,
    product: Mapping[str, Any],
    price: Mapping[str, Any] | None,
) -> dict[str, Any]:
    canonical_quantity, canonical_unit = convert_opening_quantity(
        entered_quantity,
        entered_unit_code,
        package_size=str(product["package_size"]),
        package_unit_code=str(product["package_unit_code"]),
    )
    result: dict[str, Any] = {
        "entered_quantity": decimal_string(Decimal(entered_quantity)),
        "entered_unit_code": entered_unit_code,
        "canonical_signed_quantity": canonical_quantity,
        "canonical_unit_code": canonical_unit,
        "price_status": "unavailable",
        "cost_source": "unavailable",
        "product_price_version_id": None,
        "applied_unit_price": None,
        "price_basis_unit_code": None,
        "currency": None,
        "currency_minor_unit_scale": None,
        "price_effective_from": None,
        "price_effective_to": None,
        "posted_line_amount": None,
    }
    if price is not None:
        result.update(
            {
                "price_status": "ready",
                "cost_source": "configured_effective_price",
                "product_price_version_id": str(price["id"]),
                "applied_unit_price": decimal_string(Decimal(str(price["unit_price"]))),
                "price_basis_unit_code": str(price["price_basis_unit_code"]),
                "currency": str(price["currency"]),
                "currency_minor_unit_scale": currency_minor_unit_scale(str(price["currency"])),
                "price_effective_from": str(price["effective_from"]),
                "price_effective_to": (
                    str(price["effective_to"]) if price.get("effective_to") is not None else None
                ),
                "posted_line_amount": calculate_posted_amount(
                    canonical_quantity,
                    price_basis_unit_code=str(price["price_basis_unit_code"]),
                    unit_price=str(price["unit_price"]),
                    package_size=str(product["package_size"]),
                    package_unit_code=str(product["package_unit_code"]),
                    currency=str(price["currency"]),
                ),
            }
        )
    return result


def build_receipt_line(
    *,
    entered_quantity: str,
    entered_unit_code: str,
    product: Mapping[str, Any],
    supplier_price: Mapping[str, Any] | None,
    configured_price: Mapping[str, Any] | None,
    project_currency: str,
) -> dict[str, Any]:
    """Freeze one positive supplier-receipt line using explicit price precedence."""

    if supplier_price is None:
        return build_opening_line(
            entered_quantity=entered_quantity,
            entered_unit_code=entered_unit_code,
            product=product,
            price=configured_price,
        )

    currency = str(supplier_price["currency"]).upper()
    if currency != project_currency.upper():
        raise InventoryValidationError(
            "SUPPLIER_PRICE_CURRENCY_MISMATCH",
            "supplier_price.currency",
            "Supplier price currency must match project currency.",
        )
    unit_price = _decimal(
        str(supplier_price["unit_price"]),
        code="SUPPLIER_PRICE_INVALID",
        field="supplier_price.unit_price",
    )
    if unit_price < 0:
        raise InventoryValidationError(
            "SUPPLIER_PRICE_INVALID",
            "supplier_price.unit_price",
            "Supplier price cannot be negative.",
        )
    canonical, canonical_unit = convert_opening_quantity(
        entered_quantity,
        entered_unit_code,
        package_size=str(product["package_size"]),
        package_unit_code=str(product["package_unit_code"]),
    )
    basis = str(supplier_price["price_basis_unit_code"])
    scale = currency_minor_unit_scale(currency)
    return {
        "entered_quantity": decimal_string(Decimal(entered_quantity)),
        "entered_unit_code": entered_unit_code,
        "canonical_signed_quantity": canonical,
        "canonical_unit_code": canonical_unit,
        "price_status": "ready",
        "cost_source": "supplier_document",
        "product_price_version_id": None,
        "applied_unit_price": decimal_string(unit_price),
        "price_basis_unit_code": basis,
        "currency": currency,
        "currency_minor_unit_scale": scale,
        "price_effective_from": None,
        "price_effective_to": None,
        "posted_line_amount": calculate_posted_amount(
            canonical,
            price_basis_unit_code=basis,
            unit_price=str(unit_price),
            package_size=str(product["package_size"]),
            package_unit_code=str(product["package_unit_code"]),
            currency=currency,
        ),
    }


def build_reversal_line(line: Mapping[str, Any]) -> dict[str, Any]:
    """Copy frozen authority and negate entered, canonical, and monetary values exactly."""

    result = dict(line)
    result["entered_quantity"] = decimal_string(-Decimal(str(line["entered_quantity"])))
    result["canonical_signed_quantity"] = decimal_string(
        -Decimal(str(line["canonical_signed_quantity"]))
    )
    amount = line.get("posted_line_amount")
    scale = line.get("currency_minor_unit_scale")
    result["posted_line_amount"] = (
        money_string(-Decimal(str(amount)), int(scale))
        if amount is not None and scale is not None
        else None
    )
    return result
