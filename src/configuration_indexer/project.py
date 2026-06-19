from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .detector import SourceInfo, detect_source, source_info_to_dict
from .indexer import IndexOptions, parse_configuration
from .xml_utils import safe_id_part, safe_rel, sha1_text

PROJECT_SCHEMA_VERSION = "configuration-mcp/project-bundle/1"
MANIFEST_NAME = "configuration-mcp.yaml"
EXTENSION_COLLECTION_DIRS = ("extensions", "exchanges")

TABLE_NAMES = [
    "configuration_products",
    "configuration_product_releases",
    "configuration_snapshots",
    "configuration_index_runs",
    "configuration_files",
    "configuration_objects",
    "configuration_aliases",
    "configuration_object_fields",
    "configuration_forms",
    "configuration_templates",
    "configuration_modules",
    "configuration_methods",
    "configuration_queries",
    "configuration_relations",
    "configuration_cards",
]

UNIQUE_TABLES = {"configuration_products", "configuration_product_releases", "configuration_snapshots"}


@dataclass
class ExtensionEntry:
    path: Path
    name: str = ""
    source: str = "extensions"


@dataclass
class ProjectLayout:
    root: Path
    is_valid: bool
    base_src: Path | None = None
    manifest_path: Path | None = None
    extensions: list[ExtensionEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class ProjectIndexOptions:
    project_root: Path
    include_code_text: bool = True
    base_mode: str = "index"
    client_id: str = ""
    base_id: str = ""
    base_profile_id: str = ""
    profile_name: str = ""
    standard_snapshot_id: str = ""


def detect_project(root: Path) -> ProjectLayout:
    root = Path(root)
    if not root.exists() or not root.is_dir():
        return ProjectLayout(root=root, is_valid=False, error="Project folder not found")

    manifest_path = root / MANIFEST_NAME
    base_src = root / "src"
    warnings: list[str] = []
    if not (base_src / "Configuration.xml").exists():
        return ProjectLayout(
            root=root,
            is_valid=False,
            manifest_path=manifest_path if manifest_path.exists() else None,
            warnings=warnings,
            error="Project folder must contain src/Configuration.xml",
        )

    extensions = discover_extensions(root, base_src, warnings)
    return ProjectLayout(
        root=root,
        is_valid=True,
        base_src=base_src,
        manifest_path=manifest_path if manifest_path.exists() else None,
        extensions=extensions,
        warnings=warnings,
    )


def discover_extensions(root: Path, base_src: Path, warnings: list[str]) -> list[ExtensionEntry]:
    result: list[ExtensionEntry] = []
    seen: set[Path] = set()
    seen_identities: set[tuple[str, str]] = set()

    for collection_name in EXTENSION_COLLECTION_DIRS:
        extensions_root = root / collection_name
        if not extensions_root.exists() or not extensions_root.is_dir():
            continue
        for child in sorted(extensions_root.iterdir(), key=lambda item: item.name.lower()):
            if child.is_dir() and (child / "Configuration.xml").exists():
                info = detect_source(child)
                if info.is_valid and info.source_kind == "extension":
                    result.append(ExtensionEntry(path=child, name=info.name or child.name, source=collection_name))
                    seen.add(normalized_path(child))
                    seen_identities.add(extension_identity(info, child.name))
                elif info.is_valid:
                    warnings.append(f"Skipped {safe_rel(child, root)}: source_kind={info.source_kind}")

    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or normalized_path(child) in seen or same_path(child, base_src):
            continue
        if child.name in EXTENSION_COLLECTION_DIRS or not (child / "Configuration.xml").exists():
            continue
        info = detect_source(child)
        if info.is_valid and info.source_kind == "extension":
            identity = extension_identity(info, child.name)
            if identity in seen_identities:
                warnings.append(f"Skipped duplicate extension {safe_rel(child, root)}: name={info.name or child.name}")
                continue
            result.append(ExtensionEntry(path=child, name=info.name or child.name, source="sibling"))
            seen.add(normalized_path(child))
            seen_identities.add(identity)

    return result


def extension_identity(info: SourceInfo, fallback_name: str) -> tuple[str, str]:
    name = info.name or fallback_name
    version = info.version or info.extension_compatibility_mode or ""
    return name.strip().casefold(), version.strip().casefold()


def parse_project(options: ProjectIndexOptions) -> dict:
    layout = detect_project(options.project_root)
    if not layout.is_valid or layout.base_src is None:
        raise ValueError(layout.error or "Invalid project folder")

    indexed_at = datetime.now().isoformat(timespec="seconds")
    base_source_info = detect_source(layout.base_src)
    if not base_source_info.is_valid:
        raise ValueError(base_source_info.error or "Cannot detect base src")
    base_info = source_info_to_dict(base_source_info)
    product_code = base_info.get("product_code") or "unknown"
    release_version = base_info.get("release_version") or "unknown"
    release_id = f"{product_code}:{release_version}"
    base_snapshot_id = options.standard_snapshot_id
    indexes = []
    base_objects_by_full_name = {}

    if options.base_mode == "index":
        base_index = parse_configuration(
            IndexOptions(
                src_root=layout.base_src,
                mode="standard",
                include_code_text=options.include_code_text,
            )
        )
        indexes.append(base_index)
        base_info = base_index["source_info"]
        product_code = base_index["summary"].get("product_code") or base_info.get("product_code") or product_code
        release_version = base_index["summary"].get("release_version") or base_info.get("release_version") or release_version
        release_id = f"{product_code}:{release_version}"
        base_snapshot_id = base_index["configuration_snapshots"][0]["id"]
        base_objects_by_full_name = {
            obj["full_name"]: obj for obj in base_index.get("configuration_objects", [])
        }
    elif options.base_mode != "detect":
        raise ValueError("base_mode must be index or detect")

    client_id = options.client_id or safe_id_part(layout.root.name.lower())
    base_id = options.base_id or "default"
    base_profile_id = options.base_profile_id or f"{client_id}:{base_id}"
    profile_name = options.profile_name or layout.root.name

    extension_items = []
    customizations = []
    layers = []
    if base_snapshot_id:
        layers.append(
            {
                "id": f"{base_profile_id}:layer:0000:standard",
                "base_profile_id": base_profile_id,
                "base_snapshot_id": base_snapshot_id,
                "layer_snapshot_id": base_snapshot_id,
                "release_id": release_id,
                "customization_id": None,
                "layer_kind": "standard",
                "layer_order": 0,
                "extension_name": None,
                "is_active": True,
                "status": "active",
                "metadata": {"path": safe_rel(layout.base_src, layout.root), "base_mode": options.base_mode},
            }
        )
    impacts = []

    for position, extension in enumerate(layout.extensions, start=1):
        ext_probe = detect_source(extension.path)
        extension_name_hint = ext_probe.name or extension.name or extension.path.name
        ext_snapshot_id = make_project_extension_snapshot_id(client_id, base_id, extension_name_hint, ext_probe)
        ext_index = parse_configuration(
            IndexOptions(
                src_root=extension.path,
                mode="extension",
                product_code=product_code,
                release_version=release_version,
                snapshot_id=ext_snapshot_id,
                include_code_text=options.include_code_text,
            )
        )
        indexes.append(ext_index)

        ext_info = ext_index["source_info"]
        extension_name = ext_info.get("name") or extension.name or extension.path.name
        customization_id = f"{base_profile_id}:extension:{safe_id_part(extension_name)}"
        customizations.append(
            {
                "id": customization_id,
                "client_id": client_id,
                "base_id": base_id,
                "base_profile_id": base_profile_id,
                "product_id": product_code,
                "release_id": release_id,
                "composition_snapshot_id": None,
                "snapshot_id": ext_snapshot_id,
                "customization_kind": "extension",
                "name": extension_name,
                "extension_name": extension_name,
                "version": ext_info.get("version") or ext_info.get("extension_compatibility_mode") or "",
                "source_path": str(extension.path),
                "source_repo": "",
                "source_ref": "",
                "is_active": True,
                "status": "active",
                "metadata": {
                    "path": safe_rel(extension.path, layout.root),
                    "source": extension.source,
                    "source_info": ext_info,
                },
            }
        )
        layers.append(
            {
                "id": f"{base_profile_id}:layer:{position * 10:04d}:extension:{safe_id_part(extension_name)}",
                "base_profile_id": base_profile_id,
                "base_snapshot_id": base_snapshot_id or None,
                "layer_snapshot_id": ext_snapshot_id,
                "release_id": release_id,
                "customization_id": customization_id,
                "layer_kind": "extension",
                "layer_order": position * 10,
                "extension_name": extension_name,
                "is_active": True,
                "status": "active",
                "metadata": {
                    "path": safe_rel(extension.path, layout.root),
                    "source": extension.source,
                    "requires_standard_snapshot_resolution": not bool(base_snapshot_id),
                },
            }
        )
        impacts.extend(build_extension_impacts(customization_id, ext_index, base_snapshot_id, base_objects_by_full_name))
        extension_items.append(
            {
                "path": str(extension.path),
                "relative_path": safe_rel(extension.path, layout.root),
                "source": extension.source,
                "name": extension_name,
                "snapshot_id": ext_snapshot_id,
                "summary": ext_index["summary"],
                "source_info": ext_info,
            }
        )

    merged = merge_indexes(indexes)
    base_profile = {
        "id": base_profile_id,
        "client_id": client_id,
        "base_id": base_id,
        "name": profile_name,
        "product_id": product_code,
        "release_id": release_id,
        "standard_snapshot_id": base_snapshot_id,
        "active_composition_snapshot_id": None,
        "main_source_kind": "standard_release",
        "main_version": release_version,
        "main_version_checked_at": indexed_at,
        "status": "active",
        "metadata": {
            "project_root": str(layout.root),
            "manifest_path": str(layout.root / MANIFEST_NAME),
            "base_src": safe_rel(layout.base_src, layout.root),
            "layout": "src+extensions",
        },
    }

    project_info = {
        "root": str(layout.root),
        "manifest_path": str(layout.root / MANIFEST_NAME),
        "base_src": str(layout.base_src),
        "base_mode": options.base_mode,
        "client_id": client_id,
        "base_id": base_id,
        "base_profile_id": base_profile_id,
        "profile_name": profile_name,
        "product_code": product_code,
        "release_version": release_version,
        "release_id": release_id,
        "standard_snapshot_id": base_snapshot_id,
        "extensions": extension_items,
        "warnings": layout.warnings,
    }

    merged.update(
        {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "project_info": project_info,
            "configuration_base_profiles": [base_profile],
            "configuration_client_customizations": customizations,
            "configuration_snapshot_layers": layers,
            "configuration_client_customization_impacts": impacts,
            "summary": {
                "source_kind": "project",
                "project_root": str(layout.root),
                "base_profile_id": base_profile_id,
                "product_code": product_code,
                "release_version": release_version,
                "standard_snapshot_id": base_snapshot_id,
                "base_mode": options.base_mode,
                "extensions": len(extension_items),
                "snapshots": len(merged.get("configuration_snapshots", [])),
                "objects": len(merged.get("configuration_objects", [])),
                "aliases": len(merged.get("configuration_aliases", [])),
                "fields": len(merged.get("configuration_object_fields", [])),
                "forms": len(merged.get("configuration_forms", [])),
                "templates": len(merged.get("configuration_templates", [])),
                "modules": len(merged.get("configuration_modules", [])),
                "methods": len(merged.get("configuration_methods", [])),
                "queries": len(merged.get("configuration_queries", [])),
                "relations": len(merged.get("configuration_relations", [])),
                "cards": len(merged.get("configuration_cards", [])),
                "files": len(merged.get("configuration_files", [])),
                "customizations": len(customizations),
                "layers": len(layers),
                "impacts": len(impacts),
            },
        }
    )
    return merged


def make_project_extension_snapshot_id(client_id: str, base_id: str, extension_name: str, info: SourceInfo) -> str:
    version = info.version or info.extension_compatibility_mode or "no_version"
    return ":".join(
        [
            "extension",
            safe_id_part(client_id or "client"),
            safe_id_part(base_id or "base"),
            safe_id_part(extension_name or "extension"),
            safe_id_part(version),
        ]
    )


def merge_indexes(indexes: list[dict]) -> dict:
    merged = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "indexer_version": indexes[0].get("indexer_version", "") if indexes else "",
    }
    for table in TABLE_NAMES:
        rows = []
        for index in indexes:
            rows.extend(index.get(table, []))
        if table in UNIQUE_TABLES:
            rows = unique_by_id(rows)
        merged[table] = rows
    return merged


def unique_by_id(rows: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for row in rows:
        row_id = row.get("id")
        if row_id in seen:
            continue
        seen.add(row_id)
        result.append(row)
    return result


def build_extension_impacts(
    customization_id: str,
    ext_index: dict,
    base_snapshot_id: str,
    base_objects_by_full_name: dict[str, dict],
) -> list[dict]:
    impacts = []
    snapshot_id = ext_index["configuration_snapshots"][0]["id"]
    for obj in ext_index.get("configuration_objects", []):
        metadata = obj.get("metadata") or {}
        extension_kind = metadata.get("extension_object_kind") or "own"
        target_full_name = metadata.get("extended_configuration_object") or obj.get("full_name") or ""
        target_object = base_objects_by_full_name.get(target_full_name)
        impact_kind = "extends_standard_object" if extension_kind == "adopted" else "new_extension_object"
        impacts.append(
            {
                "id": f"{customization_id}:impact:{sha1_text(obj.get('id', obj.get('full_name', '')))[:12]}",
                "customization_id": customization_id,
                "snapshot_id": snapshot_id,
                "source_entity_type": "object",
                "source_entity_id": obj.get("id"),
                "source_full_name": obj.get("full_name"),
                "target_snapshot_id": (base_snapshot_id or None) if extension_kind == "adopted" else None,
                "target_entity_type": obj.get("object_type") if extension_kind == "adopted" else None,
                "target_entity_id": target_object.get("id") if target_object else None,
                "target_full_name": target_full_name,
                "impact_kind": impact_kind,
                "confidence": 0.8 if target_object else 0.6,
                "source_location": {"path": obj.get("xml_path")},
                "status": "active",
                "metadata": {"extension_object_kind": extension_kind},
            }
        )
    return impacts


def render_project_manifest(project: dict) -> str:
    info = project["project_info"]
    lines = [
        "schema_version: \"configuration-mcp/project/1\"",
        "base:",
        "  path: \"./src\"",
        f"  product_code: {yaml_quote(info.get('product_code') or '')}",
        f"  release_version: {yaml_quote(info.get('release_version') or '')}",
        f"  standard_snapshot_id: {yaml_quote(info.get('standard_snapshot_id') or '')}",
        "profile:",
        f"  client_id: {yaml_quote(info.get('client_id') or '')}",
        f"  base_id: {yaml_quote(info.get('base_id') or '')}",
        f"  base_profile_id: {yaml_quote(info.get('base_profile_id') or '')}",
        f"  name: {yaml_quote(info.get('profile_name') or '')}",
        "extensions:",
    ]
    extensions = info.get("extensions") or []
    if not extensions:
        lines.append("  []")
    else:
        for extension in extensions:
            lines.extend(
                [
                    f"  - name: {yaml_quote(extension.get('name') or '')}",
                    f"    path: {yaml_quote('./' + (extension.get('relative_path') or '').replace(chr(92), '/'))}",
                    f"    snapshot_id: {yaml_quote(extension.get('snapshot_id') or '')}",
                ]
            )
    lines.append("")
    return "\n".join(lines)


def write_project_manifest(project: dict, manifest_path: Path | None = None) -> Path:
    path = manifest_path or Path(project["project_info"]["manifest_path"])
    path.write_text(render_project_manifest(project), encoding="utf-8")
    return path


def project_info_to_dict(layout: ProjectLayout) -> dict:
    return {
        "root": str(layout.root),
        "is_valid": layout.is_valid,
        "base_src": str(layout.base_src) if layout.base_src else "",
        "manifest_path": str(layout.manifest_path) if layout.manifest_path else "",
        "extensions": [
            {"path": str(extension.path), "name": extension.name, "source": extension.source}
            for extension in layout.extensions
        ],
        "warnings": layout.warnings,
        "error": layout.error,
    }


def source_info_for_project_base(layout: ProjectLayout) -> SourceInfo | None:
    if not layout.base_src:
        return None
    info = detect_source(layout.base_src)
    return info if info.is_valid else None


def yaml_quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def normalized_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def same_path(left: Path, right: Path) -> bool:
    return normalized_path(left) == normalized_path(right)
