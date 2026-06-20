from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from copy import deepcopy
from typing import Any

V2_SCHEMA_VERSION = "configuration-mcp/v2"

METHOD_BODY_PREVIEW_CHARS = 240
QUERY_ENTITY_PREVIEW_CHARS = 360
QUERY_CHUNK_PREVIEW_CHARS = 600
CARD_CHUNK_MAX_CHARS = 1600
MAX_QUERY_CHUNKS = 1000
MAX_TEXT_PREVIEW_ROWS = 5000
STANDARD_NAVIGATION_ENTITY_TYPES = {"object", "field", "form", "template", "module"}
STANDARD_RELATION_TYPES = {
    "external_call": "calls_object",
    "uses_metadata_object": "uses_object",
    "field_value_type": "field_type_object",
}
STANDARD_RELATIONS_PER_SOURCE_KIND = 8

V2_PACKAGED_TABLES = [
    "configuration_products",
    "configuration_product_releases",
    "configuration_snapshots",
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
    standard_snapshot_ids = standard_snapshot_ids_for(index)
    standard_source = is_standard_source(index) or bool(standard_snapshot_ids)
    include_text_previews = should_include_text_previews(index)
    entities = build_entities(
        index,
        aliases_by_entity,
        include_text_previews=include_text_previews,
        standard_snapshot_ids=standard_snapshot_ids,
        standard_navigation_only=standard_source,
    )
    entity_ids = {row["id"] for row in entities if row.get("id")}
    relations = build_relations(
        index,
        entity_ids,
        standard_snapshot_ids=standard_snapshot_ids,
        standard_navigation_only=standard_source,
    )
    chunks = build_search_chunks(index, aliases_by_entity)

    product_rows, release_rows = build_catalog_rows(index, standard_snapshot_ids)

    result: dict[str, Any] = {
        "schema_version": V2_SCHEMA_VERSION,
        "indexer_version": index.get("indexer_version", ""),
        "source_info": sanitize_source_info(index.get("source_info") or {}),
        "project_info": sanitize_json(index.get("project_info") or {}),
        "summary": sanitize_summary(index.get("summary") or {}),
        "configuration_products": product_rows,
        "configuration_product_releases": release_rows,
        "configuration_snapshots": sanitize_rows(index.get("configuration_snapshots") or []),
        "configuration_layers": build_layers(index),
        "configuration_index_runs": sanitize_rows(index.get("configuration_index_runs") or []),
        "configuration_entities": entities,
        "configuration_relations": relations,
        "configuration_search_chunks": chunks,
    }
    method_entities = sum(1 for row in entities if row.get("entity_type") == "method")
    query_entities = sum(1 for row in entities if row.get("entity_type") == "query")
    source_relations = len(index.get("configuration_relations") or [])
    result["summary"].update(
        {
            "entities": len(entities),
            "search_chunks": len(chunks),
            "query_search_chunks": sum(1 for row in chunks if row.get("chunk_type") == "query_text"),
            "query_search_chunks_omitted": max(
                0,
                len(index.get("configuration_queries") or [])
                - sum(1 for row in chunks if row.get("chunk_type") == "query_text"),
            ),
            "text_previews": include_text_previews,
            "standard_compact_profile": standard_source,
            "standard_navigation_profile": standard_source,
            "standard_navigation_entity_types": sorted(STANDARD_NAVIGATION_ENTITY_TYPES) if standard_source else [],
            "standard_relations_per_source_kind": STANDARD_RELATIONS_PER_SOURCE_KIND if standard_source else None,
            "method_entities": method_entities,
            "method_entities_omitted": max(0, len(index.get("configuration_methods") or []) - method_entities),
            "query_entities": query_entities,
            "query_entities_omitted": max(0, len(index.get("configuration_queries") or []) - query_entities),
            "relations_input_rows": source_relations,
            "relations_output_rows": len(relations),
            "relations_omitted": max(0, source_relations - len(relations)),
            "schema_version": V2_SCHEMA_VERSION,
        }
    )
    return result


def build_catalog_rows(index: dict[str, Any], standard_snapshot_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not standard_snapshot_ids:
        return [], []
    return (
        sanitize_rows(index.get("configuration_products") or []),
        sanitize_rows(index.get("configuration_product_releases") or []),
    )


def build_entities(
    index: dict[str, Any],
    aliases_by_entity: dict[str, list[str]],
    *,
    include_text_previews: bool,
    standard_snapshot_ids: set[str],
    standard_navigation_only: bool,
) -> list[dict[str, Any]]:
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
        if standard_navigation_only:
            continue
        if method.get("snapshot_id") in standard_snapshot_ids and not method.get("is_export"):
            continue
        data = compact_data(method, ["is_function", "is_export", "signature", "start_line", "end_line", "metadata"])
        body_text = method.get("body_text")
        if body_text:
            data["body_length"] = len(body_text)
            if include_text_previews:
                data["body_preview"] = first_chars(body_text, METHOD_BODY_PREVIEW_CHARS)
                data["body_omitted"] = len(body_text) > METHOD_BODY_PREVIEW_CHARS
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
        if standard_navigation_only:
            continue
        if query.get("snapshot_id") in standard_snapshot_ids:
            continue
        data = compact_data(query, ["query_kind", "path", "start_line", "end_line", "query_hash", "metadata"])
        query_text = query.get("query_text") or query.get("normalized_text")
        if query_text:
            data["query_length"] = len(query_text)
            if include_text_previews:
                data["query_preview"] = first_chars(query_text, QUERY_ENTITY_PREVIEW_CHARS)
                data["query_omitted"] = len(query_text) > QUERY_ENTITY_PREVIEW_CHARS
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


def build_relations(
    index: dict[str, Any],
    entity_ids: set[str],
    *,
    standard_snapshot_ids: set[str],
    standard_navigation_only: bool,
) -> list[dict[str, Any]]:
    rows = sanitize_rows(index.get("configuration_relations") or [])
    if standard_navigation_only:
        return build_standard_navigation_relations(index, rows)
    if not standard_snapshot_ids:
        return rows
    result = []
    for row in rows:
        source_id = row.get("source_id")
        if row.get("snapshot_id") in standard_snapshot_ids and source_id and source_id not in entity_ids:
            continue
        result.append(row)
    return result


def build_standard_navigation_relations(index: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookup = build_navigation_lookup(index)
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for row in rows:
        source_relation_type = row.get("relation_type") or ""
        relation_type = STANDARD_RELATION_TYPES.get(source_relation_type)
        if not relation_type:
            continue

        source_object_id = lookup["entity_to_object"].get(row.get("source_id") or "") or row.get("source_object_id") or ""
        target_object_id = resolve_relation_target_object(row, lookup)
        if not source_object_id or not target_object_id or source_object_id == target_object_id:
            continue

        snapshot_id = row.get("snapshot_id") or ""
        key = (snapshot_id, source_object_id, target_object_id, relation_type)
        item = grouped.get(key)
        if not item:
            item = {
                "id": "",
                "snapshot_id": snapshot_id,
                "source_type": "object",
                "source_entity_id": source_object_id,
                "source_full_name": lookup["object_names"].get(source_object_id) or row.get("source_full_name") or "",
                "target_type": "object",
                "target_entity_id": target_object_id,
                "target_full_name": lookup["object_names"].get(target_object_id) or row.get("target_full_name") or "",
                "source_object_id": source_object_id,
                "target_object_id": target_object_id,
                "source_id": source_object_id,
                "target_id": target_object_id,
                "relation_type": relation_type,
                "relation_kind": "standard_object_navigation",
                "source_name": lookup["object_names"].get(source_object_id) or row.get("source_full_name") or "",
                "target_name": lookup["object_names"].get(target_object_id) or row.get("target_full_name") or "",
                "confidence": 0.82,
                "metadata": {
                    "profile": "standard_navigation",
                    "source_relation_types": [],
                    "count": 0,
                    "samples": [],
                },
            }
            grouped[key] = item
        metadata = item["metadata"]
        metadata["count"] += 1
        if source_relation_type and source_relation_type not in metadata["source_relation_types"]:
            metadata["source_relation_types"].append(source_relation_type)
        samples = metadata["samples"]
        if len(samples) < 5:
            sample = {
                "source": row.get("source_full_name") or row.get("source_name") or "",
                "target": row.get("target_full_name") or row.get("target_name") or "",
            }
            location = sanitize_json(row.get("source_location") or {})
            if location:
                sample["location"] = location
            samples.append(sample)

    by_source_kind: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in grouped.values():
        by_source_kind[(item["source_object_id"], item["relation_type"])].append(item)

    result: list[dict[str, Any]] = []
    for items in by_source_kind.values():
        items.sort(key=lambda row: (-int(row.get("metadata", {}).get("count") or 0), row.get("target_name") or ""))
        result.extend(items[:STANDARD_RELATIONS_PER_SOURCE_KIND])

    for item in result:
        key = "|".join(
            [
                item.get("snapshot_id") or "",
                item.get("source_object_id") or "",
                item.get("target_object_id") or "",
                item.get("relation_type") or "",
            ]
        )
        item["id"] = f"{item.get('snapshot_id')}:rel:standard_navigation:{sha1_text(key)[:16]}"
        item["metadata"] = sanitize_json(item["metadata"])

    result.sort(key=lambda row: (row.get("source_name") or "", row.get("relation_type") or "", row.get("target_name") or ""))
    return result


def build_navigation_lookup(index: dict[str, Any]) -> dict[str, dict[str, str]]:
    entity_to_object: dict[str, str] = {}
    object_by_full_name: dict[str, str] = {}
    common_module_by_name: dict[str, str] = {}
    object_names: dict[str, str] = {}

    for obj in index.get("configuration_objects") or []:
        object_id = obj.get("id") or ""
        if not object_id:
            continue
        entity_to_object[object_id] = object_id
        full_name = obj.get("full_name") or obj.get("name") or ""
        if full_name:
            object_by_full_name[full_name] = object_id
            object_names[object_id] = full_name
        if obj.get("object_type") == "CommonModule" and obj.get("name"):
            common_module_by_name[obj["name"]] = object_id

    for collection_name in [
        "configuration_object_fields",
        "configuration_forms",
        "configuration_templates",
        "configuration_modules",
        "configuration_methods",
        "configuration_queries",
    ]:
        for row in index.get(collection_name) or []:
            row_id = row.get("id") or ""
            object_id = row.get("object_id") or ""
            if row_id and object_id:
                entity_to_object[row_id] = object_id

    return {
        "entity_to_object": entity_to_object,
        "object_by_full_name": object_by_full_name,
        "common_module_by_name": common_module_by_name,
        "object_names": object_names,
    }


def resolve_relation_target_object(row: dict[str, Any], lookup: dict[str, dict[str, str]]) -> str:
    target_id = row.get("target_id") or ""
    if target_id and target_id in lookup["entity_to_object"]:
        return lookup["entity_to_object"][target_id]

    target_full_name = row.get("target_full_name") or ""
    if target_full_name in lookup["object_by_full_name"]:
        return lookup["object_by_full_name"][target_full_name]

    parts = target_full_name.split(".")
    if len(parts) >= 2:
        object_full_name = ".".join(parts[:2])
        if object_full_name in lookup["object_by_full_name"]:
            return lookup["object_by_full_name"][object_full_name]

    if parts and parts[0] in lookup["common_module_by_name"]:
        return lookup["common_module_by_name"][parts[0]]

    return ""


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
                content=first_chars(text, CARD_CHUNK_MAX_CHARS),
                metadata=metadata,
            )
        )

    if should_include_query_chunks(index):
        queries_for_chunks = index.get("configuration_queries") or []
    else:
        queries_for_chunks = []

    for query in queries_for_chunks:
        query_text = query.get("normalized_text") or query.get("query_text") or ""
        if not query_text:
            continue
        content = build_query_chunk_content(query, query_text)
        chunks.append(
            search_chunk_row(
                chunk_id=f"{query.get('id')}:chunk:query",
                snapshot_id=query.get("snapshot_id"),
                entity_id=query.get("id"),
                chunk_type="query_text",
                title=query.get("full_name") or query.get("name") or "Query",
                content=content,
                metadata={
                    **compact_data(query, ["query_kind", "path", "start_line", "end_line", "query_hash"]),
                    "query_length": len(query_text),
                    "query_preview_chars": QUERY_CHUNK_PREVIEW_CHARS,
                    "full_text_source": "git_or_local_src",
                },
            )
        )

    return [row for row in chunks if row.get("id") and row.get("content")]


def should_include_text_previews(index: dict[str, Any]) -> bool:
    if is_standard_source(index):
        return False
    row_count = len(index.get("configuration_methods") or []) + len(index.get("configuration_queries") or [])
    return row_count <= MAX_TEXT_PREVIEW_ROWS


def should_include_query_chunks(index: dict[str, Any]) -> bool:
    if is_standard_source(index):
        return False
    return len(index.get("configuration_queries") or []) <= MAX_QUERY_CHUNKS


def source_kind(index: dict[str, Any]) -> str:
    summary = index.get("summary") or {}
    info = index.get("source_info") or {}
    return str(summary.get("source_kind") or info.get("source_kind") or "").strip().lower()


def is_standard_source(index: dict[str, Any]) -> bool:
    return source_kind(index) in {"standard", "configuration"}


def standard_snapshot_ids_for(index: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for row in index.get("configuration_snapshots") or []:
        scope = str(row.get("scope") or "").strip().lower()
        kind = str(row.get("source_kind") or "").strip().lower()
        if scope == "standard" or kind in {"standard", "configuration"}:
            snapshot_id = row.get("id")
            if snapshot_id:
                result.add(snapshot_id)
    if is_standard_source(index):
        summary = index.get("summary") or {}
        snapshot_id = summary.get("snapshot_id")
        if snapshot_id:
            result.add(snapshot_id)
    return result


def build_query_chunk_content(query: dict[str, Any], query_text: str) -> str:
    preview = first_chars(query_text, QUERY_CHUNK_PREVIEW_CHARS)
    omitted = len(query_text) > QUERY_CHUNK_PREVIEW_CHARS
    path = normalize_relative_path(query.get("path") or "")
    lines = [
        f"Query: {query.get('full_name') or query.get('name') or ''}",
        f"Path: {path}",
    ]
    if query.get("start_line") or query.get("end_line"):
        lines.append(f"Lines: {query.get('start_line') or ''}-{query.get('end_line') or ''}")
    if query.get("query_hash"):
        lines.append(f"Hash: {query.get('query_hash')}")
    lines.extend(
        [
            f"Preview chars: {min(len(query_text), QUERY_CHUNK_PREVIEW_CHARS)} of {len(query_text)}",
            f"Full text omitted: {str(omitted).lower()}",
            "Text preview:",
            preview,
        ]
    )
    return "\n".join(lines)


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


def build_layers(index: dict[str, Any]) -> list[dict[str, Any]]:
    project_info = index.get("project_info") or {}
    base_id = project_info.get("base_id") or ""
    if not base_id:
        return []

    result: list[dict[str, Any]] = []
    standard_snapshot_id = project_info.get("standard_snapshot_id") or ""
    packaged_snapshot_ids = {row.get("id") for row in index.get("configuration_snapshots") or [] if row.get("id")}
    release_id = project_info.get("release_id") or None
    if standard_snapshot_id and standard_snapshot_id in packaged_snapshot_ids:
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
            if key in {"root", "base_source_path", "base_src", "project_root", "manifest_path", "source_path", "path"}:
                sanitized = sanitize_source_path(child)
                if sanitized:
                    result[key] = sanitized
                continue
            result[key] = sanitize_json(child)
        return result
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str):
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


def sha1_text(value: str) -> str:
    return hashlib.sha1((value or "").encode("utf-8")).hexdigest()
