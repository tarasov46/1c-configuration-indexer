from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from typing import Any

V2_SCHEMA_VERSION = "configuration-mcp/v2"

V2_PACKAGED_TABLES = [
    "configuration_products",
    "configuration_product_releases",
    "configuration_snapshots",
    "configuration_base_bindings",
    "configuration_layers",
    "configuration_index_runs",
    "configuration_entities",
    "configuration_relations",
    "configuration_search_chunks",
]

LOCAL_PATH_RE = re.compile(r"^[a-zA-Z]:[\\/]|^/")


def to_v2_package(index: dict[str, Any]) -> dict[str, Any]:
    """Convert the verbose parser output to the compact production schema."""

    aliases_by_entity = group_aliases(index.get("configuration_aliases") or [])
    entities = build_entities(index, aliases_by_entity)
    chunks = build_search_chunks(index, aliases_by_entity)

    result: dict[str, Any] = {
        "schema_version": V2_SCHEMA_VERSION,
        "indexer_version": index.get("indexer_version", ""),
        "source_info": sanitize_source_info(index.get("source_info") or {}),
        "summary": sanitize_summary(index.get("summary") or {}),
        "configuration_products": sanitize_rows(index.get("configuration_products") or []),
        "configuration_product_releases": sanitize_rows(index.get("configuration_product_releases") or []),
        "configuration_snapshots": sanitize_rows(index.get("configuration_snapshots") or []),
        "configuration_base_bindings": build_base_bindings(index),
        "configuration_layers": build_layers(index),
        "configuration_index_runs": sanitize_rows(index.get("configuration_index_runs") or []),
        "configuration_entities": entities,
        "configuration_relations": sanitize_rows(index.get("configuration_relations") or []),
        "configuration_search_chunks": chunks,
    }
    result["summary"].update(
        {
            "entities": len(entities),
            "search_chunks": len(chunks),
            "schema_version": V2_SCHEMA_VERSION,
        }
    )
    return result


def build_entities(index: dict[str, Any], aliases_by_entity: dict[str, list[str]]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []

    for obj in index.get("configuration_objects") or []:
        aliases = aliases_by_entity.get(obj.get("id", ""), [])
        entities.append(
            entity_row(
                row=obj,
                entity_type="object",
                entity_kind=obj.get("object_type") or "",
                object_id=obj.get("id") or "",
                parent_id=None,
                aliases=aliases,
                data_keys=["object_type", "comment", "metadata"],
            )
        )

    for field in index.get("configuration_object_fields") or []:
        aliases = aliases_by_entity.get(field.get("id", ""), [])
        entities.append(
            entity_row(
                row=field,
                entity_type="field",
                entity_kind=field.get("field_kind") or "",
                object_id=field.get("object_id") or "",
                parent_id=field.get("object_id") or None,
                aliases=aliases,
                data_keys=["field_kind", "table_part", "value_type", "position", "metadata"],
            )
        )

    for form in index.get("configuration_forms") or []:
        aliases = aliases_by_entity.get(form.get("id", ""), [])
        entities.append(
            entity_row(
                row=form,
                entity_type="form",
                entity_kind=form.get("form_kind") or "",
                object_id=form.get("object_id") or "",
                parent_id=form.get("object_id") or None,
                aliases=aliases,
                path=form.get("xml_path") or form.get("path"),
                data_keys=["form_kind", "xml_path", "module_path", "metadata"],
            )
        )

    for template in index.get("configuration_templates") or []:
        aliases = aliases_by_entity.get(template.get("id", ""), [])
        entities.append(
            entity_row(
                row=template,
                entity_type="template",
                entity_kind=template.get("template_kind") or "",
                object_id=template.get("object_id") or "",
                parent_id=template.get("object_id") or None,
                aliases=aliases,
                path=template.get("path"),
                data_keys=["template_kind", "path", "metadata"],
            )
        )

    for module in index.get("configuration_modules") or []:
        entities.append(
            entity_row(
                row=module,
                entity_type="module",
                entity_kind=module.get("module_kind") or "",
                object_id=module.get("object_id") or "",
                parent_id=module.get("object_id") or module.get("form_id") or None,
                aliases=[],
                path=module.get("path"),
                hash_value=module.get("code_hash") or module.get("file_hash"),
                data_keys=["module_kind", "form_id", "path", "file_hash", "code_hash", "metadata"],
            )
        )

    for method in index.get("configuration_methods") or []:
        data = compact_data(method, ["is_function", "is_export", "signature", "start_line", "end_line", "metadata"])
        body_text = method.get("body_text")
        if body_text:
            data["body_preview"] = first_chars(body_text, 1200)
            data["body_omitted"] = len(body_text) > 1200
        entities.append(
            entity_row(
                row=method,
                entity_type="method",
                entity_kind="function" if method.get("is_function") else "procedure",
                object_id=method.get("object_id") or "",
                parent_id=method.get("module_id") or None,
                aliases=[],
                line_start=method.get("start_line"),
                line_end=method.get("end_line"),
                signature=method.get("signature"),
                data=data,
            )
        )

    for query in index.get("configuration_queries") or []:
        data = compact_data(query, ["query_kind", "path", "start_line", "end_line", "query_hash", "metadata"])
        query_text = query.get("query_text") or query.get("normalized_text")
        if query_text:
            data["query_preview"] = first_chars(query_text, 2000)
            data["query_omitted"] = len(query_text) > 2000
        entities.append(
            entity_row(
                row=query,
                entity_type="query",
                entity_kind=query.get("query_kind") or "",
                object_id=query.get("object_id") or "",
                parent_id=query.get("method_id") or query.get("module_id") or None,
                aliases=[],
                path=query.get("path"),
                line_start=query.get("start_line"),
                line_end=query.get("end_line"),
                hash_value=query.get("query_hash"),
                data=data,
            )
        )

    return [row for row in entities if row.get("id")]


def entity_row(
    row: dict[str, Any],
    entity_type: str,
    entity_kind: str,
    object_id: str,
    parent_id: str | None,
    aliases: list[str],
    path: str | None = None,
    line_start: Any = None,
    line_end: Any = None,
    signature: str | None = None,
    hash_value: str | None = None,
    data_keys: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = data if data is not None else compact_data(row, data_keys or [])
    if aliases:
        payload["aliases"] = aliases
    name = row.get("name") or ""
    full_name = row.get("full_name") or name
    synonym = row.get("synonym") or ""
    search_text = build_search_text([entity_type, entity_kind, name, full_name, synonym, *aliases, signature or ""])
    return {
        "id": row.get("id"),
        "snapshot_id": row.get("snapshot_id"),
        "entity_type": entity_type,
        "entity_kind": entity_kind,
        "object_id": object_id or None,
        "parent_id": parent_id,
        "name": name,
        "full_name": full_name,
        "synonym": synonym,
        "path": normalize_relative_path(path or row.get("path") or row.get("xml_path") or ""),
        "line_start": int_or_none(line_start),
        "line_end": int_or_none(line_end),
        "signature": signature or "",
        "hash": hash_value or row.get("hash") or "",
        "search_text": search_text,
        "data": sanitize_json(payload),
    }


def build_search_chunks(index: dict[str, Any], aliases_by_entity: dict[str, list[str]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    for card in index.get("configuration_cards") or []:
        text = card.get("text") or ""
        if not text:
            continue
        metadata = compact_data(card, ["card_type", "source", "confidence", "metadata"])
        chunks.append(
            search_chunk_row(
                chunk_id=f"{card.get('id')}:chunk:0001",
                snapshot_id=card.get("snapshot_id"),
                entity_id=card.get("object_id") or card.get("method_id") or card.get("query_id"),
                chunk_type=card.get("card_type") or "summary",
                title=card.get("title") or "",
                content=text,
                metadata=metadata,
            )
        )

    for query in index.get("configuration_queries") or []:
        query_text = query.get("query_text") or ""
        if not query_text:
            continue
        content = "\n".join(
            [
                f"Query: {query.get('full_name') or query.get('name') or ''}",
                f"Path: {normalize_relative_path(query.get('path') or '')}",
                first_chars(query_text, 6000),
            ]
        )
        chunks.append(
            search_chunk_row(
                chunk_id=f"{query.get('id')}:chunk:query",
                snapshot_id=query.get("snapshot_id"),
                entity_id=query.get("id"),
                chunk_type="query_text",
                title=query.get("full_name") or query.get("name") or "Query",
                content=content,
                metadata=compact_data(query, ["query_kind", "path", "start_line", "end_line", "query_hash"]),
            )
        )

    return [row for row in chunks if row.get("id") and row.get("content")]


def search_chunk_row(
    chunk_id: str,
    snapshot_id: str | None,
    entity_id: str | None,
    chunk_type: str,
    title: str,
    content: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    text = normalize_text(content)
    return {
        "id": chunk_id,
        "snapshot_id": snapshot_id,
        "entity_id": entity_id,
        "chunk_type": chunk_type,
        "title": title,
        "content": content,
        "search_text": build_search_text([title, text]),
        "embedding": None,
        "metadata": sanitize_json(metadata),
    }


def build_base_bindings(index: dict[str, Any]) -> list[dict[str, Any]]:
    project_info = index.get("project_info") or {}
    summary = index.get("summary") or {}
    client_id = project_info.get("client_id") or ""
    base_id = project_info.get("base_id") or ""
    if not base_id:
        return []
    product_id = project_info.get("product_code") or summary.get("product_code") or ""
    release_version = project_info.get("release_version") or summary.get("release_version") or ""
    release_id = project_info.get("release_id") or (f"{product_id}:{release_version}" if product_id and release_version else "")
    return [
        {
            "id": base_id,
            "base_id": base_id,
            "client_id": client_id,
            "product_id": product_id,
            "release_id": release_id or None,
            "standard_snapshot_id": project_info.get("standard_snapshot_id") or summary.get("standard_snapshot_id") or None,
            "status": "active",
            "metadata": sanitize_json(
                {
                    "profile_name": project_info.get("profile_name") or "",
                    "layout": "src+extensions",
                    "warnings": project_info.get("warnings") or [],
                }
            ),
        }
    ]


def build_layers(index: dict[str, Any]) -> list[dict[str, Any]]:
    project_info = index.get("project_info") or {}
    base_id = project_info.get("base_id") or ""
    if not base_id:
        return []

    result: list[dict[str, Any]] = []
    standard_snapshot_id = project_info.get("standard_snapshot_id") or ""
    release_id = project_info.get("release_id") or None
    if standard_snapshot_id:
        result.append(
            {
                "id": f"{base_id}:layer:0000:standard",
                "base_id": base_id,
                "snapshot_id": standard_snapshot_id,
                "release_id": release_id,
                "layer_kind": "standard",
                "layer_order": 0,
                "extension_name": "",
                "is_active": True,
                "status": "active",
                "metadata": {"source": "standard_release"},
            }
        )

    for position, extension in enumerate(project_info.get("extensions") or [], start=1):
        snapshot_id = extension.get("snapshot_id") or ""
        extension_name = extension.get("name") or ""
        if not snapshot_id:
            continue
        result.append(
            {
                "id": f"{base_id}:layer:{position * 10:04d}:extension:{safe_part(extension_name)}",
                "base_id": base_id,
                "snapshot_id": snapshot_id,
                "release_id": release_id,
                "layer_kind": "extension",
                "layer_order": position * 10,
                "extension_name": extension_name,
                "is_active": True,
                "status": "active",
                "metadata": {
                    "relative_path": extension.get("relative_path") or "",
                    "source": extension.get("source") or "",
                },
            }
        )
    return result


def group_aliases(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        entity_id = row.get("entity_id") or row.get("object_id") or ""
        alias = row.get("alias") or ""
        if entity_id and alias and alias not in grouped[entity_id]:
            grouped[entity_id].append(alias)
    return grouped


def compact_data(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if value in (None, "", [], {}):
            continue
        if key.endswith("_path") or key == "path":
            data[key] = normalize_relative_path(str(value))
        elif key == "metadata":
            data[key] = sanitize_json(value)
        else:
            data[key] = sanitize_json(value)
    return data


def sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sanitize_row(row) for row in rows]


def sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    copy = deepcopy(row)
    for key in ["source_path"]:
        if key in copy:
            copy[key] = sanitize_source_path(copy.get(key))
    for key in ["metadata", "source_info", "project_info", "summary"]:
        if key in copy:
            copy[key] = sanitize_json(copy.get(key))
    return copy


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key in {"root", "base_source_path", "project_root", "manifest_path", "source_path"}:
                sanitized = sanitize_source_path(child)
                if sanitized:
                    result[key] = sanitized
                continue
            result[key] = sanitize_json(child)
        return result
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str):
        if LOCAL_PATH_RE.search(value.strip()):
            return ""
        return value
    return value


def sanitize_source_info(info: dict[str, Any]) -> dict[str, Any]:
    return sanitize_json(info)


def sanitize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return sanitize_json(summary)


def sanitize_source_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if LOCAL_PATH_RE.search(text):
        return ""
    return normalize_relative_path(text)


def normalize_relative_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if LOCAL_PATH_RE.search(text):
        return ""
    return text


def build_search_text(parts: list[str]) -> str:
    return normalize_text(" ".join(str(part or "") for part in parts if part))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def first_chars(value: str, limit: int) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_part(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]+", "_", value or "").strip("_")
    return text or "layer"
