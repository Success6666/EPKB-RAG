import unittest

from app.services.mysql_repository import row_value


class MySqlSchemaHelperTests(unittest.TestCase):
    def test_row_value_is_case_insensitive_for_driver_column_names(self):
        row = {"COLUMN_NAME": "metadata_chunk_type", "Index_Name": "idx_py_chunk_scope_type_doc"}

        self.assertEqual(row_value(row, "column_name"), "metadata_chunk_type")
        self.assertEqual(row_value(row, "index_name"), "idx_py_chunk_scope_type_doc")

    def test_row_value_returns_none_for_missing_key(self):
        self.assertIsNone(row_value({"other": "value"}, "column_name"))


if __name__ == "__main__":
    unittest.main()
