from __future__ import annotations

import unittest

from configuration_indexer.v2 import to_v2_package


class V2PackageTests(unittest.TestCase):
    def test_extension_only_package_does_not_write_catalog_rows(self) -> None:
        index = {
            "summary": {"source_kind": "extension"},
            "configuration_products": [{"id": "erp", "name": "1C:ERP"}],
            "configuration_product_releases": [{"id": "erp:2.5.27.47", "product_code": "erp"}],
            "configuration_snapshots": [
                {
                    "id": "extension:base:ext:Version8_3_21",
                    "scope": "extension",
                    "source_kind": "extension",
                }
            ],
        }

        package = to_v2_package(index)

        self.assertEqual(package["configuration_products"], [])
        self.assertEqual(package["configuration_product_releases"], [])

    def test_standard_package_keeps_catalog_rows(self) -> None:
        index = {
            "summary": {"source_kind": "standard"},
            "configuration_products": [{"id": "erp", "name": "1C:ERP"}],
            "configuration_product_releases": [{"id": "erp:2.5.27.47", "product_code": "erp"}],
            "configuration_snapshots": [
                {
                    "id": "standard:erp:2.5.27.47",
                    "scope": "standard",
                    "source_kind": "standard",
                }
            ],
        }

        package = to_v2_package(index)

        self.assertEqual(len(package["configuration_products"]), 1)
        self.assertEqual(len(package["configuration_product_releases"]), 1)


if __name__ == "__main__":
    unittest.main()
