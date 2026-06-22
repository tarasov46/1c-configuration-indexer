# Продовый запуск индексатора configuration-mcp

## Что делает агент

1. Получает у пользователя путь к выгрузке или Git URL клиентского репозитория.
2. Для клиентской базы проверяет, что в client-memory есть `client_id`, `base_id` и версия конфигурации.
3. Вызывает admin MCP prepare tool и получает `data.indexing_job`.
4. Сохраняет `data.indexing_job` в `indexing-job.json`.
5. Запускает индексатор командой `configuration-indexer run-job --job indexing-job.json`.
6. Проверяет статус через admin MCP status/list tool.
7. Для клиентских проектов и расширений работает с данными, когда job перешел в `completed`.
8. Запускает embedding worker для pending chunks или передает это admin MCP/НейроКор.
9. Для типовой конфигурации дополнительно привязывает `standard_snapshot_id` к релизу через admin MCP release-link/finalize tool.

Агент не должен читать XML, BSL, jsonl, gzip chunks или большие JSON-пакеты в чат. Все тяжелые данные передает сам индексатор.

Если upload оборвался, агент не запускает парсинг заново. Нужно сохранить JSON
результата загрузки и выполнить `retry-failed-package` по тем же `manifest.json`
и upload URL. Если проблема в размере chunks, агент сначала выполняет
`rechunk-package`, а потом загружает новый пакет.

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
- `configuration_search_chunks` содержит карточки объектов, `content_hash` и статус embedding;
- поиск через `search_configuration_cards` находит объекты из нескольких расширений;
- `get_configuration_base_profile` показывает нужную версию базы и слои расширений.

## Embeddings / RAG

После upload карточки уже лежат в `configuration_search_chunks`, но могут быть в статусе `pending`. Проверить очередь:

```sql
select public.configuration_v2_embedding_queue_stats(null::text[]);
```

Запустить embedding worker из доверенного окружения:

```powershell
configuration-indexer embed-chunks `
  --supabase-url "https://<project-ref>.supabase.co" `
  --supabase-key-env SUPABASE_SERVICE_ROLE_KEY `
  --openai-api-key-env OPENAI_API_KEY `
  --model text-embedding-3-small `
  --batch-size 64
```

Если объект не изменился при повторной индексации, старый embedding сохраняется по `content_hash`. Если карточка изменилась, только этот chunk становится `pending` и переобрабатывается.

## Восстановление после сбоя загрузки

Повторить только упавшие chunks:

```powershell
configuration-indexer retry-failed-package `
  --manifest ".\out\index-package\manifest.json" `
  --failed-log ".\upload-result.json" `
  --upload-url "<upload webhook>" `
  --token-env CONFIGURATION_INDEXER_UPLOAD_TOKEN
```

Переупаковать готовый пакет без повторного чтения исходной выгрузки:

```powershell
configuration-indexer rechunk-package `
  --manifest ".\out\index-package\manifest.json" `
  --out-dir ".\out\index-package-rechunked" `
  --job-id "idx_retry_001" `
  --max-chunk-bytes 1048576
```
