"""Declarative contracts and validation schema for Olist e-commerce datasets.

Defines field-level parsers, type coercion, range validation, and dataset definitions
used by the transactional loader to safely ingest raw CSV rows into PostgreSQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, Numeric, SmallInteger, Text, Uuid
from sqlalchemy.sql import column, table


@dataclass(frozen=True)
class Field:
    """Represents a single column contract within a dataset.

    Attributes:
        name: Target database column name.
        kind: Logical type ('text', 'zip', 'state', 'uuid', 'timestamp', 'integer',
              'score', 'money', 'measure', 'coordinate').
        nullable: Whether missing or empty values are permitted (parsed as None).
        source: Upstream CSV header name if different from database column name
                (e.g., Brazilian CSV typo 'product_name_lenght' -> 'product_name_length').
        minimum: Optional lower bound constraint (inclusive).
        maximum: Optional upper bound constraint (inclusive).
        choices: Whitelist tuple of permitted string values (e.g., order statuses).
    """

    name: str
    kind: str = "text"
    nullable: bool = False
    source: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()

    @property
    def source_name(self) -> str:
        """Return the column name as it appears in the raw CSV header."""
        return self.source or self.name

    @property
    def sql_type(self) -> Any:
        """Map logical field kinds to strict SQLAlchemy column types."""
        return {
            "text": Text(),
            "zip": Text(),
            "state": Text(),
            "uuid": Uuid(),
            "timestamp": DateTime(timezone=False),
            "integer": Integer(),
            "score": SmallInteger(),
            "money": Numeric(12, 2),
            "measure": Numeric(14, 3),
            "coordinate": Numeric(),
        }[self.kind]

    def parse(self, raw: str | None) -> Any:
        """Validate and coerce a raw string value according to field rules.

        Raises:
            ValueError: If validation fails or types cannot be safely coerced.
        """
        # Handle empty/blank input according to nullability rules
        if raw is None or raw.strip() == "":
            if self.nullable:
                return None
            raise ValueError(f"{self.name}: required")

        # Strip whitespace for non-text fields; preserve verbatim text
        value: Any = raw.strip() if self.kind != "text" else raw

        try:
            if self.kind == "uuid":
                value = UUID(value)
            elif self.kind == "timestamp":
                # Parse ISO-8601 timestamps and verify they are timezone-naive
                value = datetime.fromisoformat(value)
                if value.tzinfo is not None:
                    raise ValueError("Olist timestamps must be timezone-naive")
            elif self.kind in {"integer", "score"}:
                # Parse via Decimal to prevent floating-point truncation issues
                number = Decimal(value)
                if not number.is_finite() or number != number.to_integral_value():
                    raise ValueError("expected integer")
                value = int(number)
                if not -(2**31) <= value < 2**31:
                    raise ValueError("integer overflow")
            elif self.kind in {"money", "measure", "coordinate"}:
                # Fixed-point decimal arithmetic for monetary and physical measures
                value = Decimal(value)
                if not value.is_finite():
                    raise ValueError("non-finite number")
                if self.minimum is not None and value < self.minimum:
                    raise ValueError("below minimum")
                if self.maximum is not None and value > self.maximum:
                    raise ValueError("above maximum")
                if self.kind == "coordinate":
                    rounded = value
                else:
                    precision, scale = {"money": (12, 2), "measure": (14, 3)}[self.kind]
                    rounded = value.quantize(Decimal(1).scaleb(-scale))
                    if rounded != value:
                        raise ValueError("excess decimal precision")
                    if abs(rounded) >= Decimal(10) ** (precision - scale):
                        raise ValueError("numeric overflow")
                value = rounded
            elif self.kind == "zip":
                # Ensure 1 to 5 digits and pad leading zeros to exactly 5 digits
                if not re.fullmatch(r"[0-9]{1,5}", value):
                    raise ValueError("invalid ZIP prefix")
                value = value.zfill(5)
            elif self.kind == "state":
                # 2-letter uppercase Brazilian UF state code
                if not re.fullmatch(r"[A-Z]{2}", value):
                    raise ValueError("invalid state")

            # Check bounds and enum memberships
            if self.minimum is not None and value < self.minimum:
                raise ValueError("below minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("above maximum")
            if self.choices and value not in self.choices:
                raise ValueError("unknown value")

            # PostgreSQL text fields reject NUL (\x00) characters
            if isinstance(value, str) and "\x00" in value:
                raise ValueError("NUL is not supported by PostgreSQL text")

            return value
        except (ValueError, InvalidOperation, OverflowError) as exc:
            raise ValueError(f"{self.name}: {exc}") from exc


@dataclass(frozen=True)
class Dataset:
    """Represents an Olist dataset contract matching a CSV and relational table.

    Attributes:
        name: Table name in the `olist` schema.
        filename: CSV filename in the `data/raw/` directory.
        fields: Tuple of declared Field specifications.
        key: Primary key column name(s).
        references: Foreign key dependencies as ((column_name, parent_dataset_name), ...).
    """

    name: str
    filename: str
    fields: tuple[Field, ...]
    key: tuple[str, ...] = ()
    references: tuple[tuple[str, str], ...] = ()

    @property
    def sql_table(self) -> Any:
        """Construct an anonymous SQLAlchemy Table object for batch insertion."""
        return table(self.name, *(column(f.name, f.sql_type) for f in self.fields), schema="olist")


def nonnegative(name: str, kind: str = "integer", source: str | None = None) -> Field:
    """Factory helper for nullable non-negative metrics."""
    return Field(name, kind, nullable=True, source=source, minimum=0)


# Complete declarative definition of all 9 Olist datasets in strict dependency order:
# Translations -> Customers -> Sellers -> Products -> Orders -> Items -> Payments -> Reviews -> Geolocation
DATASETS = (
    Dataset(
        "category_translations",
        "product_category_name_translation.csv",
        (
            Field("product_category_name"),
            Field("product_category_name_english"),
        ),
        key=("product_category_name",),
    ),
    Dataset(
        "customers",
        "olist_customers_dataset.csv",
        (
            Field("customer_id", "uuid"),
            Field("customer_unique_id", "uuid"),
            Field("customer_zip_code_prefix", "zip"),
            Field("customer_city"),
            Field("customer_state", "state"),
        ),
        key=("customer_id",),
    ),
    Dataset(
        "sellers",
        "olist_sellers_dataset.csv",
        (
            Field("seller_id", "uuid"),
            Field("seller_zip_code_prefix", "zip"),
            Field("seller_city"),
            Field("seller_state", "state"),
        ),
        key=("seller_id",),
    ),
    Dataset(
        "products",
        "olist_products_dataset.csv",
        (
            Field("product_id", "uuid"),
            Field("product_category_name", nullable=True),
            nonnegative("product_name_length", source="product_name_lenght"),
            nonnegative("product_description_length", source="product_description_lenght"),
            nonnegative("product_photos_qty"),
            nonnegative("product_weight_g", "measure"),
            nonnegative("product_length_cm", "measure"),
            nonnegative("product_height_cm", "measure"),
            nonnegative("product_width_cm", "measure"),
        ),
        key=("product_id",),
        references=(("product_category_name", "category_translations"),),
    ),
    Dataset(
        "orders",
        "olist_orders_dataset.csv",
        (
            Field("order_id", "uuid"),
            Field("customer_id", "uuid"),
            Field(
                "order_status",
                choices=(
                    "created",
                    "approved",
                    "invoiced",
                    "processing",
                    "shipped",
                    "delivered",
                    "unavailable",
                    "canceled",
                ),
            ),
            Field("order_purchase_timestamp", "timestamp"),
            *(
                Field(name, "timestamp", nullable=True)
                for name in (
                    "order_approved_at",
                    "order_delivered_carrier_date",
                    "order_delivered_customer_date",
                    "order_estimated_delivery_date",
                )
            ),
        ),
        key=("order_id",),
        references=(("customer_id", "customers"),),
    ),
    Dataset(
        "order_items",
        "olist_order_items_dataset.csv",
        (
            Field("order_id", "uuid"),
            Field("order_item_id", "integer", minimum=1),
            Field("product_id", "uuid"),
            Field("seller_id", "uuid"),
            Field("shipping_limit_date", "timestamp"),
            Field("price", "money", minimum=0),
            Field("freight_value", "money", minimum=0),
        ),
        key=("order_id", "order_item_id"),
        references=(
            ("order_id", "orders"),
            ("product_id", "products"),
            ("seller_id", "sellers"),
        ),
    ),
    Dataset(
        "order_payments",
        "olist_order_payments_dataset.csv",
        (
            Field("order_id", "uuid"),
            Field("payment_sequential", "integer", minimum=1),
            Field(
                "payment_type",
                choices=("credit_card", "boleto", "voucher", "debit_card", "not_defined"),
            ),
            Field("payment_installments", "integer", minimum=0),
            Field("payment_value", "money", minimum=0),
        ),
        key=("order_id", "payment_sequential"),
        references=(("order_id", "orders"),),
    ),
    Dataset(
        "order_reviews",
        "olist_order_reviews_dataset.csv",
        (
            Field("review_id", "uuid"),
            Field("order_id", "uuid"),
            Field("review_score", "score", minimum=1, maximum=5),
            Field("review_comment_title", nullable=True),
            Field("review_comment_message", nullable=True),
            Field("review_creation_date", "timestamp"),
            Field("review_answer_timestamp", "timestamp", nullable=True),
        ),
        key=("review_id", "order_id"),
        references=(("order_id", "orders"),),
    ),
    Dataset(
        "geolocation",
        "olist_geolocation_dataset.csv",
        (
            Field("geolocation_zip_code_prefix", "zip"),
            Field("geolocation_lat", "coordinate", minimum=-90, maximum=90),
            Field("geolocation_lng", "coordinate", minimum=-180, maximum=180),
            Field("geolocation_city"),
            Field("geolocation_state", "state"),
        ),
    ),
)
