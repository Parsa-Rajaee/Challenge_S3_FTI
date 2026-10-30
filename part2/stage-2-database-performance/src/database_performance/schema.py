"""Explicit source contracts shared by validation and typed SQL inserts."""

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
    name: str
    kind: str = "text"
    nullable: bool = False
    source: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()

    @property
    def source_name(self) -> str:
        return self.source or self.name

    @property
    def sql_type(self) -> Any:
        return {
            "text": Text(), "zip": Text(), "state": Text(), "uuid": Uuid(),
            "timestamp": DateTime(timezone=False), "integer": Integer(),
            "score": SmallInteger(), "money": Numeric(12, 2),
            "measure": Numeric(14, 3), "coordinate": Numeric(),
        }[self.kind]

    def parse(self, raw: str | None) -> Any:
        if raw is None or raw.strip() == "":
            if self.nullable:
                return None
            raise ValueError(f"{self.name}: required")
        value: Any = raw.strip() if self.kind != "text" else raw
        try:
            if self.kind == "uuid":
                value = UUID(value)
            elif self.kind == "timestamp":
                value = datetime.fromisoformat(value)
                if value.tzinfo is not None:
                    raise ValueError("Olist timestamps must be timezone-naive")
            elif self.kind in {"integer", "score"}:
                number = Decimal(value)
                if not number.is_finite() or number != number.to_integral_value():
                    raise ValueError("expected integer")
                value = int(number)
                if not -(2**31) <= value < 2**31:
                    raise ValueError("integer overflow")
            elif self.kind in {"money", "measure", "coordinate"}:
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
                if not re.fullmatch(r"[0-9]{1,5}", value):
                    raise ValueError("invalid ZIP prefix")
                value = value.zfill(5)
            elif self.kind == "state" and not re.fullmatch(r"[A-Z]{2}", value):
                raise ValueError("invalid state")
            if self.minimum is not None and value < self.minimum:
                raise ValueError("below minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("above maximum")
            if self.choices and value not in self.choices:
                raise ValueError("unknown value")
            if isinstance(value, str) and "\x00" in value:
                raise ValueError("NUL is not supported by PostgreSQL text")
            return value
        except (ValueError, InvalidOperation, OverflowError) as exc:
            raise ValueError(f"{self.name}: {exc}") from exc


@dataclass(frozen=True)
class Dataset:
    name: str
    filename: str
    fields: tuple[Field, ...]
    key: tuple[str, ...] = ()
    references: tuple[tuple[str, str], ...] = ()

    @property
    def sql_table(self) -> Any:
        return table(self.name, *(column(f.name, f.sql_type) for f in self.fields), schema="olist")


def nonnegative(name: str, kind: str = "integer", source: str | None = None) -> Field:
    return Field(name, kind, nullable=True, source=source, minimum=0)


DATASETS = (
    Dataset("category_translations", "product_category_name_translation.csv", (
        Field("product_category_name"), Field("product_category_name_english"),
    ), ("product_category_name",)),
    Dataset("customers", "olist_customers_dataset.csv", (
        Field("customer_id", "uuid"), Field("customer_unique_id", "uuid"),
        Field("customer_zip_code_prefix", "zip"), Field("customer_city"), Field("customer_state", "state"),
    ), ("customer_id",)),
    Dataset("sellers", "olist_sellers_dataset.csv", (
        Field("seller_id", "uuid"), Field("seller_zip_code_prefix", "zip"),
        Field("seller_city"), Field("seller_state", "state"),
    ), ("seller_id",)),
    Dataset("products", "olist_products_dataset.csv", (
        Field("product_id", "uuid"), Field("product_category_name", nullable=True),
        nonnegative("product_name_length", source="product_name_lenght"),
        nonnegative("product_description_length", source="product_description_lenght"),
        nonnegative("product_photos_qty"), nonnegative("product_weight_g", "measure"),
        nonnegative("product_length_cm", "measure"), nonnegative("product_height_cm", "measure"),
        nonnegative("product_width_cm", "measure"),
    ), ("product_id",), (("product_category_name", "category_translations"),)),
    Dataset("orders", "olist_orders_dataset.csv", (
        Field("order_id", "uuid"), Field("customer_id", "uuid"),
        Field("order_status", choices=("created", "approved", "invoiced", "processing", "shipped", "delivered", "unavailable", "canceled")),
        Field("order_purchase_timestamp", "timestamp"),
        *(Field(name, "timestamp", nullable=True) for name in (
            "order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"
        )),
    ), ("order_id",), (("customer_id", "customers"),)),
    Dataset("order_items", "olist_order_items_dataset.csv", (
        Field("order_id", "uuid"), Field("order_item_id", "integer", minimum=1),
        Field("product_id", "uuid"), Field("seller_id", "uuid"), Field("shipping_limit_date", "timestamp"),
        Field("price", "money", minimum=0), Field("freight_value", "money", minimum=0),
    ), ("order_id", "order_item_id"), (("order_id", "orders"), ("product_id", "products"), ("seller_id", "sellers"))),
    Dataset("order_payments", "olist_order_payments_dataset.csv", (
        Field("order_id", "uuid"), Field("payment_sequential", "integer", minimum=1),
        Field("payment_type", choices=("credit_card", "boleto", "voucher", "debit_card", "not_defined")),
        Field("payment_installments", "integer", minimum=0), Field("payment_value", "money", minimum=0),
    ), ("order_id", "payment_sequential"), (("order_id", "orders"),)),
    Dataset("order_reviews", "olist_order_reviews_dataset.csv", (
        Field("review_id", "uuid"), Field("order_id", "uuid"), Field("review_score", "score", minimum=1, maximum=5),
        Field("review_comment_title", nullable=True), Field("review_comment_message", nullable=True),
        Field("review_creation_date", "timestamp"), Field("review_answer_timestamp", "timestamp", nullable=True),
    ), ("review_id", "order_id"), (("order_id", "orders"),)),
    Dataset("geolocation", "olist_geolocation_dataset.csv", (
        Field("geolocation_zip_code_prefix", "zip"),
        Field("geolocation_lat", "coordinate", minimum=-90, maximum=90),
        Field("geolocation_lng", "coordinate", minimum=-180, maximum=180),
        Field("geolocation_city"), Field("geolocation_state", "state"),
    )),
)
