from __future__ import annotations

import unittest

from configuration_indexer.bsl import extract_call_relations


class BslCallTests(unittest.TestCase):
    def test_external_calls_skip_parameters_assigned_variables_and_chain_middle(self) -> None:
        relations = extract_call_relations(
            method_identifier="method:1",
            method_full_name="Object.Module.Печать",
            body="""
Процедура Печать(КоллекцияПечатныхФорм) Экспорт
    Команды = Новый ТаблицаЗначений;
    Команды.Колонки.Добавить("Представление");
    КоллекцияПечатныхФорм.Добавить();
    УправлениеПечатью.ВывестиТабличныйДокументВКоллекцию();
КонецПроцедуры
""",
            path="ObjectModule.bsl",
            start_line=1,
            snapshot_id="snapshot",
            local_methods={},
            ignored_external_targets={"КоллекцияПечатныхФорм"},
        )

        targets = [relation["target_full_name"] for relation in relations]

        self.assertEqual(targets, ["УправлениеПечатью.ВывестиТабличныйДокументВКоллекцию"])


if __name__ == "__main__":
    unittest.main()
