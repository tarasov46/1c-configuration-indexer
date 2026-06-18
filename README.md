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

Preferred:

```text
project-root/
  src/
    Configuration.xml
  extensions/
    ExtensionName/
      Configuration.xml
```

Legacy sibling extension folders are also detected:

```text
project-root/
  src/
  src exchange/
```

## Autonomous Job

MCP should return a small job JSON. Example:

[examples/indexing-job.example.json](examples/indexing-job.example.json)

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
      configuration_objects.000001.jsonl.gz
      configuration_methods.000001.jsonl.gz
      configuration_queries.000001.jsonl.gz
      configuration_cards.000001.jsonl.gz
```

## Upload Existing Package

```powershell
.\.venv\Scripts\configuration-indexer.exe upload-package `
  --manifest ".\out\index-package\manifest.json" `
  --upload-url "https://example.com/configuration-index-upload" `
  --token-env CONFIGURATION_INDEXER_UPLOAD_TOKEN
```

Upload protocol:

- `POST` manifest with header `X-Configuration-Upload-Part: manifest`
- `POST` each gzip chunk with header `X-Configuration-Upload-Part: chunk`
- `POST` completion marker with header `X-Configuration-Upload-Part: complete`

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
  --out-dir ".\out" `
  --no-code-text
```

## Safety

Do not commit 1C exports, generated packages, `.cf`, `.cfe`, `.dt`, or tokens.
