from __future__ import annotations

import gzip
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request

from .package import read_manifest, sha256_file


@dataclass
class PackageUploadOptions:
    manifest_path: Path
    upload_url: str
    token: str = ""
    token_env: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout_seconds: float = 300
    send_complete: bool = True
    transport: str = "binary"
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    stop_on_chunk_failure: bool = True


@dataclass
class PackageUploadResult:
    ok: bool
    manifest_status: int | None = None
    complete_status: int | None = None
    uploaded_chunks: int = 0
    failed_chunks: list[dict[str, Any]] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "manifest_status": self.manifest_status,
            "complete_status": self.complete_status,
            "uploaded_chunks": self.uploaded_chunks,
            "failed_chunks": self.failed_chunks,
            "responses": self.responses,
            "error": self.error,
        }


def upload_package(options: PackageUploadOptions) -> PackageUploadResult:
    manifest_path = Path(options.manifest_path)
    manifest = read_manifest(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    package_dir = manifest_path.parent
    result = PackageUploadResult(ok=False)

    try:
        manifest_response = post_bytes(
            options,
            data=json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Configuration-Upload-Part": "manifest",
                "X-Configuration-Job-Id": str(manifest.get("job_id") or ""),
                "X-Configuration-Package-Schema": str(manifest.get("schema_version") or ""),
                "X-Configuration-Manifest-Sha256": manifest_sha256,
            },
        )
        result.manifest_status = manifest_response["status_code"]
        result.responses.append(manifest_response)
        if not manifest_response["ok"]:
            result.error = "manifest upload failed"
            return result
        if response_data(manifest_response).get("already_completed") is True:
            result.ok = True
            return result

        chunks = manifest.get("chunks") or []
        for position, chunk in enumerate(chunks, start=1):
            chunk_path = package_dir / chunk["file"]
            response = post_chunk_with_retries(options, manifest, chunk, chunk_path, position, len(chunks))
            result.responses.append(response)
            if response["ok"]:
                result.uploaded_chunks += 1
            else:
                result.failed_chunks.append({"chunk": chunk, "response": response})
                if options.stop_on_chunk_failure:
                    result.error = f"chunk upload failed: {chunk.get('file') or ''}"
                    return result

        if result.failed_chunks:
            result.error = "one or more chunks failed"
            return result

        if options.send_complete:
            complete_response = post_bytes(
                options,
                data=json.dumps(
                    {
                        "job_id": manifest.get("job_id"),
                        "chunk_count": len(chunks),
                        "row_count": manifest.get("row_count"),
                        "package_bytes": manifest.get("package_bytes"),
                        "manifest_sha256": manifest_sha256,
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Configuration-Upload-Part": "complete",
                    "X-Configuration-Job-Id": str(manifest.get("job_id") or ""),
                },
            )
            result.complete_status = complete_response["status_code"]
            result.responses.append(complete_response)
            if not complete_response["ok"]:
                result.error = "complete upload failed"
                return result

        result.ok = True
        return result
    except Exception as exc:
        result.error = str(exc)
        return result


def retry_failed_chunks(options: PackageUploadOptions, failed_log_path: Path) -> PackageUploadResult:
    manifest_path = Path(options.manifest_path)
    manifest = read_manifest(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    package_dir = manifest_path.parent
    result = PackageUploadResult(ok=False)

    try:
        failed_chunks = failed_chunks_from_log(Path(failed_log_path), manifest)
        chunks = manifest.get("chunks") or []
        positions_by_file = {str(chunk.get("file") or ""): position for position, chunk in enumerate(chunks, start=1)}

        for chunk in failed_chunks:
            chunk_path = package_dir / chunk["file"]
            position = positions_by_file.get(str(chunk.get("file") or ""), int(chunk.get("chunk_index") or 1))
            response = post_chunk_with_retries(options, manifest, chunk, chunk_path, position, len(chunks))
            result.responses.append(response)
            if response["ok"]:
                result.uploaded_chunks += 1
            else:
                result.failed_chunks.append({"chunk": chunk, "response": response})
                if options.stop_on_chunk_failure:
                    result.error = f"chunk retry failed: {chunk.get('file') or ''}"
                    return result

        if result.failed_chunks:
            result.error = "one or more chunk retries failed"
            return result

        if options.send_complete:
            complete_response = post_bytes(
                options,
                data=json.dumps(
                    {
                        "job_id": manifest.get("job_id"),
                        "chunk_count": len(chunks),
                        "row_count": manifest.get("row_count"),
                        "package_bytes": manifest.get("package_bytes"),
                        "manifest_sha256": manifest_sha256,
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Configuration-Upload-Part": "complete",
                    "X-Configuration-Job-Id": str(manifest.get("job_id") or ""),
                },
            )
            result.complete_status = complete_response["status_code"]
            result.responses.append(complete_response)
            if not complete_response["ok"]:
                result.error = "complete upload failed"
                return result

        result.ok = True
        return result
    except Exception as exc:
        result.error = str(exc)
        return result


def failed_chunks_from_log(failed_log_path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    payload = json.loads(Path(failed_log_path).read_text(encoding="utf-8-sig"))
    raw_failed = payload.get("failed_chunks") or []
    manifest_chunks_by_file = {str(chunk.get("file") or ""): chunk for chunk in manifest.get("chunks") or []}
    table_order = {
        "configuration_products": 10,
        "configuration_product_releases": 20,
        "configuration_snapshots": 30,
        "configuration_layers": 40,
        "configuration_index_runs": 50,
        "configuration_entities": 60,
        "configuration_relations": 70,
        "configuration_search_chunks": 80,
    }

    chunks: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for entry in raw_failed:
        chunk = entry.get("chunk") if isinstance(entry, dict) else None
        if not isinstance(chunk, dict):
            continue
        file_name = str(chunk.get("file") or "")
        if not file_name or file_name in seen_files:
            continue
        seen_files.add(file_name)
        chunks.append(dict(manifest_chunks_by_file.get(file_name) or chunk))

    return sorted(
        chunks,
        key=lambda chunk: (
            table_order.get(str(chunk.get("table") or ""), 999),
            int(chunk.get("chunk_index") or 0),
            str(chunk.get("file") or ""),
        ),
    )


def post_chunk_with_retries(
    options: PackageUploadOptions,
    manifest: dict[str, Any],
    chunk: dict[str, Any],
    chunk_path: Path,
    position: int,
    chunk_count: int,
) -> dict[str, Any]:
    attempts = max(1, int(options.max_retries or 1))
    response: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        response = post_chunk(options, manifest, chunk, chunk_path, position, chunk_count)
        if response["ok"] or not is_retryable_response(response) or attempt == attempts:
            return response
        time.sleep(max(0.0, float(options.retry_delay_seconds or 0)) * attempt)
    return response


def post_chunk(
    options: PackageUploadOptions,
    manifest: dict[str, Any],
    chunk: dict[str, Any],
    chunk_path: Path,
    position: int,
    chunk_count: int,
) -> dict[str, Any]:
    if normalized_transport(options.transport) == "staged-json":
        return post_staged_json_chunk(options, manifest, chunk, chunk_path, position, chunk_count)
    return post_bytes(
        options,
        data=chunk_path.read_bytes(),
        headers={
            "Content-Type": chunk.get("content_type") or "application/jsonl",
            "Content-Encoding": chunk.get("content_encoding") or "gzip",
            "X-Configuration-Upload-Part": "chunk",
            "X-Configuration-Job-Id": str(manifest.get("job_id") or ""),
            "X-Configuration-Chunk-Number": str(position),
            "X-Configuration-Chunk-Count": str(chunk_count),
            "X-Configuration-Chunk-Table": str(chunk.get("table") or ""),
            "X-Configuration-Chunk-File": str(chunk.get("file") or ""),
            "X-Configuration-Chunk-Sha256": str(chunk.get("sha256") or ""),
            "X-Configuration-Chunk-Rows": str(chunk.get("rows") or 0),
        },
    )


def is_retryable_response(response: dict[str, Any]) -> bool:
    status_code = int(response.get("status_code") or 0)
    if status_code == 0 or status_code == 408 or status_code == 429:
        return True
    return 500 <= status_code <= 599


def normalized_transport(value: str) -> str:
    transport = (value or "binary").strip().lower().replace("_", "-")
    if transport in {"staged-json", "json", "json-staging", "n8n-json"}:
        return "staged-json"
    return "binary"


def post_staged_json_chunk(
    options: PackageUploadOptions,
    manifest: dict[str, Any],
    chunk: dict[str, Any],
    chunk_path: Path,
    position: int,
    chunk_count: int,
) -> dict[str, Any]:
    rows = read_gzip_jsonl(chunk_path)
    payload = {
        "job_id": manifest.get("job_id"),
        "file_path": chunk.get("file"),
        "table_name": chunk.get("table"),
        "chunk_number": position,
        "chunk_count": chunk_count,
        "sha256": chunk.get("sha256"),
        "compressed_bytes": chunk.get("bytes"),
        "raw_bytes": chunk.get("raw_bytes"),
        "rows_count": chunk.get("rows"),
        "rows": rows,
    }
    return post_bytes(
        options,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Configuration-Upload-Part": "chunk-json",
            "X-Configuration-Job-Id": str(manifest.get("job_id") or ""),
            "X-Configuration-Chunk-Number": str(position),
            "X-Configuration-Chunk-Count": str(chunk_count),
            "X-Configuration-Chunk-Table": str(chunk.get("table") or ""),
            "X-Configuration-Chunk-File": str(chunk.get("file") or ""),
            "X-Configuration-Chunk-Sha256": str(chunk.get("sha256") or ""),
            "X-Configuration-Chunk-Rows": str(chunk.get("rows") or 0),
        },
    )


def read_gzip_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def post_bytes(options: PackageUploadOptions, data: bytes, headers: dict[str, str]) -> dict[str, Any]:
    merged_headers = {
        "User-Agent": "1c-configuration-indexer",
        **headers,
    }
    token = resolve_token(options)
    if token:
        merged_headers[options.auth_header] = f"{options.auth_scheme} {token}" if options.auth_scheme else token

    req = request.Request(options.upload_url, data=data, headers=merged_headers, method="POST")
    try:
        with request.urlopen(req, timeout=options.timeout_seconds) as response:
            response_text = response.read(4096).decode("utf-8", errors="replace")
            response_json = parse_response_json(response_text)
            return {
                "ok": 200 <= response.status < 300 and response_json.get("ok", True) is not False,
                "status_code": response.status,
                "response_text": response_text,
                "response_json": response_json or None,
            }
    except error.HTTPError as exc:
        response_text = exc.read(4096).decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "response_text": response_text,
            "response_json": parse_response_json(response_text) or None,
            "error": str(exc),
        }


def resolve_token(options: PackageUploadOptions) -> str:
    if options.token:
        return options.token
    if options.token_env:
        return os.getenv(options.token_env, "")
    return ""


def parse_response_json(response_text: str) -> dict[str, Any]:
    try:
        value = json.loads(response_text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def response_data(response: dict[str, Any]) -> dict[str, Any]:
    payload = response.get("response_json")
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}
