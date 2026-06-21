from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from copy import deepcopy
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


def rechunk_package(source_manifest_path: Path, package_dir: Path, max_chunk_bytes: int, job_id: str = "") -> dict[str, Any]:
    source_manifest_path = Path(source_manifest_path)
    source_manifest = read_manifest(source_manifest_path)
    source_package_dir = source_manifest_path.parent
    package_dir = Path(package_dir)
    chunks_dir = package_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    max_chunk_bytes = max(128 * 1024, int(max_chunk_bytes or DEFAULT_MAX_CHUNK_BYTES))
    manifest = deepcopy(source_manifest)
    manifest["job_id"] = job_id or source_manifest.get("job_id") or f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    manifest["created_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["rechunked_from_job_id"] = source_manifest.get("job_id") or ""
    manifest["rechunked_from_manifest"] = str(source_manifest_path)
    manifest.pop("manifest_path", None)

    chunks: list[dict[str, Any]] = []
    for table in ordered_tables_from_manifest(source_manifest):
        table_chunks = [chunk for chunk in source_manifest.get("chunks") or [] if chunk.get("table") == table]
        chunks.extend(rechunk_table(table, table_chunks, source_package_dir, chunks_dir, max_chunk_bytes))

    manifest["chunks"] = chunks
    manifest["chunk_count"] = len(chunks)
    manifest["row_count"] = sum(chunk["rows"] for chunk in chunks)
    manifest["package_bytes"] = sum(chunk["bytes"] for chunk in chunks)

    manifest_path = package_dir / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def ordered_tables_from_manifest(manifest: dict[str, Any]) -> list[str]:
    tables: list[str] = []
    seen: set[str] = set()
    for chunk in manifest.get("chunks") or []:
        table = str(chunk.get("table") or "")
        if table and table not in seen:
            seen.add(table)
            tables.append(table)
    return tables


def rechunk_table(
    table: str,
    source_chunks: list[dict[str, Any]],
    source_package_dir: Path,
    chunks_dir: Path,
    max_chunk_bytes: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_lines: list[bytes] = []
    current_bytes = 0
    chunk_index = 1

    for source_chunk in source_chunks:
        source_path = source_package_dir / str(source_chunk.get("file") or "")
        with gzip.open(source_path, "rb") as f:
            for line in f:
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


def build_manifest(index: dict[str, Any], options: PackageOptions) -> dict[str, Any]:
    project_info = index.get("project_info") or {}
    source_info = index.get("source_info") or {}
    summary = index.get("summary") or {}
    job_id = options.job_id or f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    snapshots = index.get("configuration_snapshots") or []
    snapshot_ids = [row.get("id") for row in snapshots if row.get("id")]
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
        "snapshot_ids": snapshot_ids,
        "snapshot_count": len(snapshot_ids),
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
