from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .v2 import V2_PACKAGED_TABLES, to_v2_package

PACKAGE_SCHEMA_VERSION = "configuration-mcp/index-package/1"
DEFAULT_MAX_CHUNK_BYTES = 4 * 1024 * 1024

PACKAGED_TABLES = V2_PACKAGED_TABLES


@dataclass
class PackageOptions:
    package_dir: Path
    max_chunk_bytes: int = DEFAULT_MAX_CHUNK_BYTES
    job_id: str = ""


def write_index_package(index: dict[str, Any], options: PackageOptions) -> dict[str, Any]:
    index = to_v2_package(index)
    package_dir = Path(options.package_dir)
    chunks_dir = package_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    max_chunk_bytes = max(128 * 1024, int(options.max_chunk_bytes or DEFAULT_MAX_CHUNK_BYTES))
    manifest = build_manifest(index, options)
    chunks = []

    for table in PACKAGED_TABLES:
        rows = index.get(table)
        if not rows:
            continue
        table_chunks = write_table_chunks(table, rows, chunks_dir, max_chunk_bytes)
        chunks.extend(table_chunks)

    manifest["chunks"] = chunks
    manifest["chunk_count"] = len(chunks)
    manifest["row_count"] = sum(chunk["rows"] for chunk in chunks)
    manifest["package_bytes"] = sum(chunk["bytes"] for chunk in chunks)

    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_manifest(index: dict[str, Any], options: PackageOptions) -> dict[str, Any]:
    project_info = index.get("project_info") or {}
    source_info = index.get("source_info") or {}
    summary = index.get("summary") or {}
    job_id = options.job_id or f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "job_id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "index_schema_version": index.get("schema_version", ""),
        "indexer_version": index.get("indexer_version", ""),
        "source_kind": summary.get("source_kind") or source_info.get("source_kind") or "",
        "product_code": summary.get("product_code") or project_info.get("product_code") or source_info.get("product_code") or "",
        "release_version": summary.get("release_version") or project_info.get("release_version") or source_info.get("release_version") or "",
        "standard_snapshot_id": summary.get("standard_snapshot_id") or project_info.get("standard_snapshot_id") or "",
        "summary": summary,
        "project_info": project_info,
        "source_info": source_info,
        "chunks": [],
    }


def write_table_chunks(table: str, rows: list[dict[str, Any]], chunks_dir: Path, max_chunk_bytes: int) -> list[dict[str, Any]]:
    chunks = []
    current_lines: list[bytes] = []
    current_bytes = 0
    chunk_index = 1

    for row in rows:
        line = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if current_lines and current_bytes + len(line) > max_chunk_bytes:
            chunks.append(write_chunk(table, chunk_index, current_lines, chunks_dir))
            chunk_index += 1
            current_lines = []
            current_bytes = 0
        current_lines.append(line)
        current_bytes += len(line)

    if current_lines:
        chunks.append(write_chunk(table, chunk_index, current_lines, chunks_dir))
    return chunks


def write_chunk(table: str, chunk_index: int, lines: list[bytes], chunks_dir: Path) -> dict[str, Any]:
    file_name = f"{table}.{chunk_index:06d}.jsonl.gz"
    path = chunks_dir / file_name
    raw = b"".join(lines)
    with gzip.open(path, "wb") as f:
        f.write(raw)
    return {
        "table": table,
        "file": f"chunks/{file_name}",
        "chunk_index": chunk_index,
        "rows": len(lines),
        "bytes": path.stat().st_size,
        "raw_bytes": len(raw),
        "sha256": sha256_file(path),
        "content_type": "application/jsonl",
        "content_encoding": "gzip",
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
