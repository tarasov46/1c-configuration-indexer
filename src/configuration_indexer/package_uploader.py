from __future__ import annotations

import json
import os
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

        chunks = manifest.get("chunks") or []
        for position, chunk in enumerate(chunks, start=1):
            chunk_path = package_dir / chunk["file"]
            response = post_bytes(
                options,
                data=chunk_path.read_bytes(),
                headers={
                    "Content-Type": chunk.get("content_type") or "application/jsonl",
                    "Content-Encoding": chunk.get("content_encoding") or "gzip",
                    "X-Configuration-Upload-Part": "chunk",
                    "X-Configuration-Job-Id": str(manifest.get("job_id") or ""),
                    "X-Configuration-Chunk-Number": str(position),
                    "X-Configuration-Chunk-Count": str(len(chunks)),
                    "X-Configuration-Chunk-Table": str(chunk.get("table") or ""),
                    "X-Configuration-Chunk-File": str(chunk.get("file") or ""),
                    "X-Configuration-Chunk-Sha256": str(chunk.get("sha256") or ""),
                    "X-Configuration-Chunk-Rows": str(chunk.get("rows") or 0),
                },
            )
            result.responses.append(response)
            if response["ok"]:
                result.uploaded_chunks += 1
            else:
                result.failed_chunks.append({"chunk": chunk, "response": response})

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
            return {
                "ok": 200 <= response.status < 300,
                "status_code": response.status,
                "response_text": response_text,
            }
    except error.HTTPError as exc:
        response_text = exc.read(4096).decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "response_text": response_text,
            "error": str(exc),
        }


def resolve_token(options: PackageUploadOptions) -> str:
    if options.token:
        return options.token
    if options.token_env:
        return os.getenv(options.token_env, "")
    return ""
