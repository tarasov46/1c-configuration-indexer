# 1c-configuration-indexer

Local CLI indexer for 1C XML/BSL exports.

The user-facing flow is simple:

```text
User gives a folder.
Agent gets an indexing job from configuration-mcp.
Agent runs this indexer.
Indexer builds chunks and uploads them.
MCP imports the package into Supabase/RAG.
```

The agent must not read large payload files into the model context. Large data is moved by the indexer process over HTTP.

## Install

```powershell
git clone https://github.com/tarasov46/1c-configuration-indexer.git
cd 1c-configuration-indexer
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Project Layout

The project root can contain `src`, `exchanges`, or both.

```text
project-root/
  src/
    Configuration.xml
  exchanges/
    ExtensionName/
      Configuration.xml
```

`src` is the exported standard/base configuration. `exchanges` contains exported extensions.

An extensions-only folder is also valid when the job provides `product_code`, `release_version`, and usually `standard_snapshot_id`:

```text
exchanges/
  ExtensionName/
    Configuration.xml
  AnotherExtension/
    Configuration.xml
```

Arbitrary sibling folders such as `src exchange` are ignored; put extensions under `exchanges`.

## Autonomous Job

MCP should return a small job JSON. Example:

[examples/indexing-job.example.json](examples/indexing-job.example.json)

Production flow for an agent:

1. Call the admin configuration MCP prepare tool.
2. Save `data.indexing_job` as `indexing-job.json`.
3. Run this indexer with `run-job`.
4. Check the job with the admin MCP status tool.
5. For client projects and extensions, use the data after the upload job is `completed`.
6. For standard releases, link the imported standard snapshot to the product release with the admin MCP release-link/finalize tool.

The job must contain enough context for extensions-only projects:

- `input.source_path`: local project root, `src`, or `exchanges` folder.
- `input.product_code`: for example `erp`.
- `input.release_version`: for example `2.5.27.47`.
- `input.standard_snapshot_id`: for example `standard:erp:2.5.27.47` when the standard release is known.

Relative paths in `indexing-job.json` are resolved from the job file directory. This lets an agent clone a source repository next to the indexer and use paths such as `..\configuration-src`.

Russian production runbook: [docs/agent-runbook.ru.md](docs/agent-runbook.ru.md)

Run it:

```powershell
.\.venv\Scripts\configuration-indexer.exe run-job --job .\indexing-job.json
```

For local testing without upload:

```powershell
.\.venv\Scripts\configuration-indexer.exe run-job --job .\indexing-job.json --no-upload
```

The result is an index package:

```text
out/
  index-package-.../
    manifest.json
    chunks/
      configuration_entities.000001.jsonl.gz
      configuration_relations.000001.jsonl.gz
      configuration_search_chunks.000001.jsonl.gz
```

The package format is compact v2:

- `configuration_entities` stores navigation entities in one table.
- `configuration_search_chunks` stores RAG-ready text chunks without requiring embeddings during upload.
- Each search chunk has a stable `content_hash` / `embedding_text_hash`. Re-indexing the same object keeps its existing embedding when the card text did not change; changed cards go back to `pending`.
- `configuration_relations` stores compact references between entities.
- Client-memory `bases` remains the source of truth for `base_id`, `client_id`, configuration name, and configuration version.
- Snapshot ids are stable: standard releases use `standard:<product>:<version>`, and project extensions use `extension:<client>:<base>:<extension>:<version>`. Re-indexing the same source is a replacement, not an ever-growing history.
- `manifest.json` contains `snapshot_ids`; the upload side can purge old rows for those snapshots before importing fresh chunks.
- Local paths such as `C:\Users\...` are stripped from package metadata before upload.
- Full BSL/query text is not the database source of truth. Supabase stores path, line numbers, hashes, lengths and short previews; exact code stays in Git/src.
- Standard configurations use a compact navigation profile: object cards, objects, fields, forms, templates, modules, and top aggregated object-level relations. Full method/query rows are intentionally omitted for standard releases.
- Extensions and small client customizations stay detailed because client changes are the main analysis surface.

## RAG Embeddings

Upload is intentionally separated from embedding generation. The indexer uploads compact object cards first; embeddings are built afterward from `configuration_search_chunks.content` through Supabase RPCs. XML/BSL source files are never sent through chat.

Queue status:

```sql
select public.configuration_v2_embedding_queue_stats(null::text[]);
```

Run embeddings from a trusted admin environment:

```powershell
.\.venv\Scripts\configuration-indexer.exe embed-chunks `
  --supabase-url "https://<project-ref>.supabase.co" `
  --supabase-key-env SUPABASE_SERVICE_ROLE_KEY `
  --openai-api-key-env OPENAI_API_KEY `
  --model text-embedding-3-small `
  --batch-size 64
```

For a single snapshot:

```powershell
.\.venv\Scripts\configuration-indexer.exe embed-chunks `
  --supabase-url "https://<project-ref>.supabase.co" `
  --snapshot-id "standard:erp:2.5.27.47" `
  --limit 500
```

After a large first embedding pass, create the vector index once:

```sql
select public.configuration_v2_create_search_chunk_embedding_index();
```

Search tools can use `configuration_v2_search_chunks_hybrid`: pass normal query text, and optionally a query embedding string when the MCP workflow is ready to do vector search.

## Upload Existing Package

```powershell
.\.venv\Scripts\configuration-indexer.exe upload-package `
  --manifest ".\out\index-package\manifest.json" `
  --upload-url "https://example.com/configuration-index-upload" `
  --token-env CONFIGURATION_INDEXER_UPLOAD_TOKEN
```

`upload-package` retries transient chunk failures by default. It stops on the
first unrecoverable chunk error so the agent can inspect the result JSON and
retry only the failed pieces instead of starting the whole import again.

Upload protocol:

- `POST` manifest with header `X-Configuration-Upload-Part: manifest`
- `POST` each gzip chunk with header `X-Configuration-Upload-Part: chunk`
- `POST` completion marker with header `X-Configuration-Upload-Part: complete`

## Recovery Commands

Retry only failed chunks from a saved upload result:

```powershell
.\.venv\Scripts\configuration-indexer.exe retry-failed-package `
  --manifest ".\out\index-package\manifest.json" `
  --failed-log ".\upload-result.json" `
  --upload-url "https://example.com/configuration-index-upload" `
  --token-env CONFIGURATION_INDEXER_UPLOAD_TOKEN
```

Rebuild an existing package with smaller chunk files without reparsing the
original 1C export:

```powershell
.\.venv\Scripts\configuration-indexer.exe rechunk-package `
  --manifest ".\out\index-package\manifest.json" `
  --out-dir ".\out\index-package-rechunked" `
  --job-id "idx_retry_001" `
  --max-chunk-bytes 1048576
```

## Debug Commands

Detect one export:

```powershell
.\.venv\Scripts\configuration-indexer.exe detect --src "C:\path\to\src-or-extension"
```

Detect a project folder:

```powershell
.\.venv\Scripts\configuration-indexer.exe detect-project --root "C:\path\to\project-root"
```

Write one debug JSON:

```powershell
.\.venv\Scripts\configuration-indexer.exe run-project `
  --root "C:\path\to\project-root" `
  --product-code erp `
  --release-version 2.5.27.47 `
  --out-dir ".\out" `
  --no-code-text
```

## Safety

Do not commit 1C exports, generated packages, `.cf`, `.cfe`, `.dt`, or tokens.
