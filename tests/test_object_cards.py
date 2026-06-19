from __future__ import annotations

import unittest
from pathlib import Path

from configuration_indexer.detector import SourceInfo
from configuration_indexer.indexer import build_cards


class ObjectCardTests(unittest.TestCase):
    def test_compact_object_card_has_navigation_without_queries(self) -> None:
        snapshot_id = "extension:client:base:EFSOL_ЗУП:Version8_3_21"
        object_id = f"{snapshot_id}:DataProcessor:ES_ПечатнаяФормаПриказа"
        module_id = f"{object_id}:module:DataProcessors/ES_ПечатнаяФормаПриказа/Ext/ObjectModule.bsl"
        print_method_id = f"{module_id}:method:Печать:59"
        helper_method_id = f"{module_id}:method:ПолучитьТаблицуКоманд:25"

        cards = build_cards(
            snapshot_id,
            objects=[
                {
                    "id": object_id,
                    "snapshot_id": snapshot_id,
                    "object_type": "DataProcessor",
                    "name": "ES_ПечатнаяФормаПриказа",
                    "full_name": "DataProcessor.ES_ПечатнаяФормаПриказа",
                    "synonym": "Печатная форма приказа",
                    "comment": "",
                    "xml_path": "DataProcessors/ES_ПечатнаяФормаПриказа.xml",
                    "file_hash": "xml-hash",
                    "metadata": {"uuid": "uuid-1", "extension_object_kind": "own"},
                }
            ],
            fields=[],
            forms=[],
            templates=[
                {
                    "id": f"{object_id}:template:ПФ_MXL",
                    "object_id": object_id,
                    "name": "ПФ_MXL",
                    "path": "DataProcessors/ES_ПечатнаяФормаПриказа/Templates/ПФ_MXL.xml",
                }
            ],
            modules=[
                {
                    "id": module_id,
                    "object_id": object_id,
                    "module_kind": "ObjectModule",
                    "name": "ObjectModule",
                    "path": "DataProcessors/ES_ПечатнаяФормаПриказа/Ext/ObjectModule.bsl",
                    "code_hash": "module-hash",
                    "metadata": {"lines": 190},
                }
            ],
            methods=[
                {
                    "id": helper_method_id,
                    "object_id": object_id,
                    "name": "ПолучитьТаблицуКоманд",
                    "is_export": False,
                    "signature": "Функция ПолучитьТаблицуКоманд()",
                    "start_line": 25,
                    "end_line": 40,
                },
                {
                    "id": print_method_id,
                    "object_id": object_id,
                    "name": "Печать",
                    "is_export": True,
                    "signature": "Процедура Печать(МассивОбъектов, КоллекцияПечатныхФорм, ОбъектыПечати, ПараметрыВыводы) Экспорт",
                    "start_line": 59,
                    "end_line": 70,
                },
            ],
            relations=[
                {
                    "source_type": "method",
                    "source_id": print_method_id,
                    "relation_type": "external_call",
                    "target_full_name": "УправлениеПечатью.СоздатьКоллекциюКомандПечати",
                },
                {
                    "source_type": "method",
                    "source_id": print_method_id,
                    "relation_type": "local_call",
                    "target_id": helper_method_id,
                    "target_full_name": "DataProcessor.ES_ПечатнаяФормаПриказа.ObjectModule.ПолучитьТаблицуКоманд",
                },
            ],
            info=SourceInfo(
                root=Path("."),
                is_valid=True,
                source_kind="extension",
                confidence=1,
                name="EFSOL_ЗУП",
                synonym="EFSOL ЗУП",
            ),
            source_kind="extension",
        )

        self.assertEqual(len(cards), 1)
        text = cards[0]["text"]
        self.assertIn("Объект: DataProcessor.ES_ПечатнаяФормаПриказа", text)
        self.assertIn("Тип: обработка (DataProcessor)", text)
        self.assertIn("Слой: расширение EFSOL ЗУП", text)
        self.assertIn("Принадлежность: собственный объект расширения", text)
        self.assertIn("Методы:", text)
        self.assertIn("Зависимости:", text)
        self.assertIn("УправлениеПечатью.СоздатьКоллекциюКомандПечати", text)
        self.assertIn("ПолучитьТаблицуКоманд", text)
        self.assertIn("Файлы:", text)
        self.assertIn("Контроль изменений:", text)
        self.assertIn("Навигация:", text)
        self.assertNotIn("Найдено запросов", text)
        self.assertNotIn("Запросы", text)
        self.assertEqual(cards[0]["metadata"]["format"], "compact_object_card/v1")


if __name__ == "__main__":
    unittest.main()
