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

    def test_standard_package_uses_compact_navigation_profile(self) -> None:
        snapshot_id = "standard:erp:2.5.27.47"
        doc_id = f"{snapshot_id}:Document:ЗаказКлиента"
        module_id = f"{doc_id}:module:ObjectModule.bsl"
        method_id = f"{module_id}:method:Печать:10"
        target_id = f"{snapshot_id}:CommonModule:ПечатьДокументов"
        field_id = f"{doc_id}:field:Партнер"
        catalog_id = f"{snapshot_id}:Catalog:Партнеры"
        index = {
            "summary": {"source_kind": "standard", "snapshot_id": snapshot_id},
            "configuration_snapshots": [
                {
                    "id": snapshot_id,
                    "scope": "standard",
                    "source_kind": "standard",
                }
            ],
            "configuration_objects": [
                {"id": doc_id, "snapshot_id": snapshot_id, "object_type": "Document", "name": "ЗаказКлиента", "full_name": "Document.ЗаказКлиента"},
                {"id": target_id, "snapshot_id": snapshot_id, "object_type": "CommonModule", "name": "ПечатьДокументов", "full_name": "CommonModule.ПечатьДокументов"},
                {"id": catalog_id, "snapshot_id": snapshot_id, "object_type": "Catalog", "name": "Партнеры", "full_name": "Catalog.Партнеры"},
            ],
            "configuration_object_fields": [
                {
                    "id": field_id,
                    "snapshot_id": snapshot_id,
                    "object_id": doc_id,
                    "name": "Партнер",
                    "full_name": "Document.ЗаказКлиента.Партнер",
                    "field_kind": "attribute",
                    "value_type": "Catalog.Партнеры",
                }
            ],
            "configuration_forms": [
                {
                    "id": f"{doc_id}:form:ФормаДокумента",
                    "snapshot_id": snapshot_id,
                    "object_id": doc_id,
                    "name": "ФормаДокумента",
                    "full_name": "Document.ЗаказКлиента.Form.ФормаДокумента",
                    "form_kind": "object",
                }
            ],
            "configuration_modules": [
                {
                    "id": module_id,
                    "snapshot_id": snapshot_id,
                    "object_id": doc_id,
                    "name": "ObjectModule",
                    "full_name": "Document.ЗаказКлиента.ObjectModule",
                    "module_kind": "object",
                }
            ],
            "configuration_methods": [
                {
                    "id": method_id,
                    "snapshot_id": snapshot_id,
                    "object_id": doc_id,
                    "module_id": module_id,
                    "name": "Печать",
                    "full_name": "Document.ЗаказКлиента.ObjectModule.Печать",
                    "is_function": False,
                    "is_export": True,
                    "signature": "Процедура Печать() Экспорт",
                }
            ],
            "configuration_queries": [
                {
                    "id": f"{method_id}:query:1",
                    "snapshot_id": snapshot_id,
                    "object_id": doc_id,
                    "method_id": method_id,
                    "name": "Query",
                    "full_name": "Document.ЗаказКлиента.ObjectModule.Печать.Query",
                    "query_text": "ВЫБРАТЬ 1",
                }
            ],
            "configuration_relations": [
                {
                    "id": "rel1",
                    "snapshot_id": snapshot_id,
                    "source_type": "method",
                    "source_id": method_id,
                    "source_full_name": "Document.ЗаказКлиента.ObjectModule.Печать",
                    "relation_type": "external_call",
                    "target_type": "bsl_call",
                    "target_full_name": "ПечатьДокументов.СформироватьПечатнуюФорму",
                },
                {
                    "id": "rel2",
                    "snapshot_id": snapshot_id,
                    "source_type": "field",
                    "source_id": field_id,
                    "source_full_name": "Document.ЗаказКлиента.Партнер",
                    "relation_type": "field_value_type",
                    "target_type": "Catalog",
                    "target_full_name": "Catalog.Партнеры",
                },
                {
                    "id": "rel3",
                    "snapshot_id": snapshot_id,
                    "source_type": "method",
                    "source_id": method_id,
                    "source_full_name": "Document.ЗаказКлиента.ObjectModule.Печать",
                    "relation_type": "local_call",
                    "target_type": "method",
                    "target_id": method_id,
                    "target_full_name": "Document.ЗаказКлиента.ObjectModule.Печать",
                },
            ],
            "configuration_cards": [
                {
                    "id": f"{doc_id}:card:object_summary",
                    "snapshot_id": snapshot_id,
                    "object_id": doc_id,
                    "card_type": "object_summary",
                    "title": "Document ЗаказКлиента",
                    "text": "Объект: Document.ЗаказКлиента",
                }
            ],
        }

        package = to_v2_package(index)

        entity_types = {row["entity_type"] for row in package["configuration_entities"]}
        self.assertIn("object", entity_types)
        self.assertIn("field", entity_types)
        self.assertIn("form", entity_types)
        self.assertIn("module", entity_types)
        self.assertNotIn("method", entity_types)
        self.assertNotIn("query", entity_types)

        relation_types = {row["relation_type"] for row in package["configuration_relations"]}
        self.assertEqual(relation_types, {"calls_object", "field_type_object"})
        for relation in package["configuration_relations"]:
            self.assertEqual(relation["source_type"], "object")
            self.assertEqual(relation["target_type"], "object")
            self.assertEqual(relation["source_full_name"], "Document.ЗаказКлиента")
            self.assertTrue(relation["target_full_name"])
            self.assertEqual(relation["source_entity_id"], doc_id)
            self.assertIn(relation["target_entity_id"], {target_id, catalog_id})
            self.assertEqual(relation["relation_kind"], "standard_object_navigation")

        self.assertEqual(len(package["configuration_search_chunks"]), 1)
        self.assertTrue(package["summary"]["standard_navigation_profile"])
        self.assertEqual(package["summary"]["method_entities"], 0)
        self.assertEqual(package["summary"]["query_entities"], 0)


if __name__ == "__main__":
    unittest.main()
