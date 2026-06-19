# Продовый запуск индексатора configuration-mcp

## Что делает агент

1. Получает у пользователя путь к выгрузке или Git URL клиентского репозитория.
2. Для клиентской базы проверяет, что в client-memory есть `client_id`, `base_id` и версия конфигурации.
3. Вызывает admin MCP prepare tool и получает `data.indexing_job`.
4. Сохраняет `data.indexing_job` в `indexing-job.json`.
5. Запускает индексатор командой `configuration-indexer run-job --job indexing-job.json`.
6. Проверяет статус через admin MCP status/list tool.
7. После успешной загрузки применяет job через admin MCP apply tool.

Агент не должен читать XML, BSL, jsonl, gzip chunks или большие JSON-пакеты в чат. Все тяжелые данные передает сам индексатор.

## Поддерживаемая структура папок

```text
project-root/
  src/
    Configuration.xml
  exchanges/
    ExtensionName/
      Configuration.xml
```

Можно передавать:

- корень проекта с `src` и `exchanges`;
- только `src`;
- только `exchanges`;
- папку одного расширения с `Configuration.xml`.

Папки вида `src exchange` не индексируются. Расширения должны лежать в `exchanges`.

## Обязательный контекст для расширений

Если индексируется только `exchanges`, job должен содержать:

- `input.product_code`, например `erp`;
- `input.release_version`, например `2.5.27.47`;
- `input.standard_snapshot_id`, например `standard:erp:2.5.27.47`, если типовая версия известна.

Версия клиентской базы хранится в client-memory `bases.configuration_version`. Индексатор не должен заводить отдельную таблицу баз.

## Git-сценарий

Если исходники лежат в Git, агент клонирует клиентский репозиторий рядом с индексатором, например:

```text
work/
  configuration-src/
  1c-configuration-indexer/
    indexing-job.json
```

В этом случае `input.source_path` может быть относительным: `..\configuration-src` или `..\configuration-src\exchanges`.

## Проверка результата

Минимально проверить:

- job завершился без ошибок;
- `configuration_entities` содержит объекты/методы/формы;
- `configuration_search_chunks` содержит карточки объектов;
- поиск через `search_configuration_cards` находит объекты из нескольких расширений;
- `get_configuration_base_profile` показывает нужную версию базы и слои расширений.
