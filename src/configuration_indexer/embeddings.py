from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


@dataclass
class EmbeddingWorkerOptions:
    supabase_url: str
    supabase_key: str = ""
    supabase_key_env: str = "SUPABASE_SERVICE_ROLE_KEY"
    openai_api_key: str = ""
    openai_api_key_env: str = "OPENAI_API_KEY"
    openai_base_url: str = "https://api.openai.com/v1"
    model: str = DEFAULT_OPENAI_EMBEDDING_MODEL
    batch_size: int = 64
    limit: int = 0
    snapshot_ids: list[str] = field(default_factory=list)
    retry_failed_after_minutes: int = 60
    sleep_seconds: float = 0.0
    timeout_seconds: float = 120.0


def run_embedding_worker(options: EmbeddingWorkerOptions) -> dict[str, Any]:
    supabase_key = options.supabase_key or os.getenv(options.supabase_key_env, "")
    openai_key = options.openai_api_key or os.getenv(options.openai_api_key_env, "")
    if not options.supabase_url:
        return {"ok": False, "error": "supabase_url is required"}
    if not supabase_key:
        return {"ok": False, "error": f"Supabase key is required; set --supabase-key or {options.supabase_key_env}"}
    if not openai_key:
        return {"ok": False, "error": f"OpenAI API key is required; set --openai-api-key or {options.openai_api_key_env}"}

    processed = 0
    failed = 0
    batches = 0
    last_claim: list[dict[str, Any]] = []

    while True:
        remaining = max(options.limit - processed, 0) if options.limit > 0 else options.batch_size
        if options.limit > 0 and remaining <= 0:
            break

        claim_limit = min(max(options.batch_size, 1), remaining) if options.limit > 0 else max(options.batch_size, 1)
        claim = supabase_rpc(
            options.supabase_url,
            supabase_key,
            "configuration_v2_claim_embedding_batch",
            {
                "p_limit": claim_limit,
                "p_model": options.model,
                "p_snapshot_ids": options.snapshot_ids or None,
                "p_retry_failed_after_minutes": options.retry_failed_after_minutes,
            },
            timeout_seconds=options.timeout_seconds,
        )
        if not claim.get("ok", False):
            return {"ok": False, "error": claim.get("error") or "Failed to claim embedding batch", "summary": summarize(processed, failed, batches)}

        rows = ((claim.get("data") or {}).get("chunks") or []) if isinstance(claim.get("data"), dict) else []
        last_claim = rows
        if not rows:
            break

        batches += 1
        try:
            embeddings = create_openai_embeddings(
                openai_key=openai_key,
                base_url=options.openai_base_url,
                model=options.model,
                texts=[row.get("content") or "" for row in rows],
                timeout_seconds=options.timeout_seconds,
            )
            store_rows = []
            for row, embedding in zip(rows, embeddings, strict=True):
                store_rows.append(
                    {
                        "id": row.get("id"),
                        "content_hash": row.get("content_hash"),
                        "embedding_text_hash": row.get("embedding_text_hash"),
                        "embedding": vector_literal(embedding),
                    }
                )
            stored = supabase_rpc(
                options.supabase_url,
                supabase_key,
                "configuration_v2_store_chunk_embeddings",
                {"p_rows": store_rows, "p_model": options.model},
                timeout_seconds=options.timeout_seconds,
            )
            if not stored.get("ok", False):
                raise RuntimeError(str(stored.get("error") or "Failed to store embeddings"))
            processed += int(((stored.get("data") or {}).get("updated") or 0))
        except Exception as exc:  # pragma: no cover - network recovery path
            failed += len(rows)
            error_rows = [
                {
                    "id": row.get("id"),
                    "content_hash": row.get("content_hash"),
                    "embedding_text_hash": row.get("embedding_text_hash"),
                    "error": str(exc),
                }
                for row in rows
            ]
            supabase_rpc(
                options.supabase_url,
                supabase_key,
                "configuration_v2_store_chunk_embedding_errors",
                {"p_rows": error_rows, "p_model": options.model},
                timeout_seconds=options.timeout_seconds,
            )

        if options.sleep_seconds > 0:
            time.sleep(options.sleep_seconds)

    return {
        "ok": True,
        "summary": summarize(processed, failed, batches),
        "last_claimed": len(last_claim),
    }


def summarize(processed: int, failed: int, batches: int) -> dict[str, int]:
    return {"processed": processed, "failed": failed, "batches": batches}


def create_openai_embeddings(
    *,
    openai_key: str,
    base_url: str,
    model: str,
    texts: list[str],
    timeout_seconds: float,
) -> list[list[float]]:
    payload = {"model": model, "input": texts}
    response = post_json(
        f"{base_url.rstrip('/')}/embeddings",
        payload,
        {
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json",
        },
        timeout_seconds=timeout_seconds,
    )
    data = response.get("data") or []
    data.sort(key=lambda item: int(item.get("index") or 0))
    embeddings = [item.get("embedding") for item in data]
    if len(embeddings) != len(texts) or any(not isinstance(item, list) for item in embeddings):
        raise RuntimeError("OpenAI embeddings response does not match requested input batch")
    return embeddings


def supabase_rpc(
    supabase_url: str,
    supabase_key: str,
    function_name: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    response = post_json(
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/{function_name}",
        payload,
        {
            "Authorization": f"Bearer {supabase_key}",
            "apikey": supabase_key,
            "Content-Type": "application/json",
        },
        timeout_seconds=timeout_seconds,
    )
    if isinstance(response, dict):
        return response
    return {"ok": False, "error": f"Unexpected RPC response: {type(response).__name__}"}


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], *, timeout_seconds: float) -> Any:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {raw}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc.reason}") from exc
    if not raw.strip():
        return {}
    return json.loads(raw)


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"
