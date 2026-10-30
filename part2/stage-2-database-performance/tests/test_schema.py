"""Offline tests for source type and integrity validation."""

import sys
import unittest
from pathlib import Path
from decimal import Decimal
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database_performance.schema import DATASETS, Field


class FieldValidationTests(unittest.TestCase):
    def test_uuid_is_parsed_as_uuid(self):
        value = Field("customer_id", "uuid").parse("123e4567-e89b-12d3-a456-426614174000")
        self.assertEqual(value, UUID("123e4567-e89b-12d3-a456-426614174000"))

    def test_optional_empty_number_maps_to_null(self):
        self.assertIsNone(Field("weight", "measure", nullable=True, minimum=0).parse(""))

    def test_required_empty_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "required"):
            Field("payment_value", "money").parse("")

    def test_non_finite_and_negative_values_are_rejected(self):
        for value in ("NaN", "Infinity", "-1.00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Field("price", "money", minimum=0).parse(value)

    def test_money_precision_is_checked_before_insert(self):
        with self.assertRaisesRegex(ValueError, "precision"):
            Field("price", "money", minimum=0).parse("1.234")

    def test_coordinates_preserve_source_decimal_precision(self):
        value = Field("latitude", "coordinate", minimum=-90, maximum=90).parse("-23.456789123456")
        self.assertEqual(value, Decimal("-23.456789123456"))

    def test_zip_prefix_preserves_leading_zeroes(self):
        self.assertEqual(Field("zip", "zip").parse("123"), "00123")

    def test_source_typos_are_mapped_to_designed_column_names(self):
        products = next(dataset for dataset in DATASETS if dataset.name == "products")
        fields = {field.name: field for field in products.fields}
        self.assertEqual(fields["product_name_length"].source_name, "product_name_lenght")
        self.assertEqual(fields["product_description_length"].source_name, "product_description_lenght")

    def test_review_composite_key_preserves_duplicate_source_review_ids(self):
        reviews = next(dataset for dataset in DATASETS if dataset.name == "order_reviews")
        self.assertEqual(reviews.key, ("review_id", "order_id"))


if __name__ == "__main__":
    unittest.main()
