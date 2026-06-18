from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .bsl import extract_queries, extract_relations, normalize_query, parse_bsl_methods
from .detector import SourceInfo, detect_source, source_info_to_dict
from .xml_utils import (
    child,
    child_text,
    children,
    first_metadata_node,
    local_name,
    localized_text,
    props,
    read_xml,
    safe_id_part,
    safe_rel,
    sha1_file,
    sha1_text,
    type_text,
)

SCHEMA_VERSION = "configuration-mcp/1"
TYPE_REF_PATTERNS = [
    ("Catalog", re.compile(r"cfg:CatalogRef\.([A-Za-zА-Яа-яЁё0-9_]+)")),
    ("Document", re.compile(r"cfg:DocumentRef\.([A-Za-zА-Яа-яЁё0-9_]+)")),
    ("Enum", re.compile(r"cfg:EnumRef\.([A-Za-zА-Яа-яЁё0-9_]+)")),
    ("InformationRegister", re.compile(r"cfg:InformationRegisterRecord\.([A-Za-zА-Яа-яЁё0-9_]+)")),
    ("AccumulationRegister", re.compile(r"cfg:AccumulationRegisterRecord\.([A-Za-zА-Яа-яЁё0-9_]+)")),
]


@dataclass
class IndexOptions:
    src_root: Path
    mode: str = "auto"
    product_code: str = ""
    release_version: str = ""
    snapshot_id: str = ""
    include_code_text: bool = True


def make_snapshot_id(info: SourceInfo, mode: str, product_code: str = "", release_version: str = "") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    kind = mode if mode != "auto" else info.source_kind
    if kind in {"configuration", "standard"} and product_code and release_version:
        return f"standard:{safe_id_part(product_code)}:{safe_id_part(release_version)}"
    name = safe_id_part(info.name or "configuration")
    version = safe_id_part(info.version or info.extension_compatibility_mode or "no_version")
    return f"{kind}:{name}:{version}:{timestamp}"


def object_id(snapshot_id: str, object_type: str, name: str) -> str:
    return f"{snapshot_id}:{object_type}:{name}"


def entity_hash_id(prefix: str, value: str) -> str:
    return f"{prefix}:{sha1_text(value)[:12]}"


def parse_configuration(options: IndexOptions) -> dict:
    src_root = Path(options.src_root)
    info = detect_source(src_root)
    if not info.is_valid:
        raise ValueError(info.error)

    effective_mode = info.source_kind if options.mode == "auto" else options.mode
    product_code = options.product_code or info.product_code or "unknown"
    release_version = options.release_version or info.release_version or "unknown"
    snapshot_id = options.snapshot_id or make_snapshot_id(info, effective_mode, product_code, release_version)
    release_internal_name = info.base_name or info.name
    release_synonym = info.base_synonym or info.synonym
    release_vendor = info.base_vendor or info.vendor
    release_compatibility_mode = info.base_compatibility_mode or info.compatibility_mode
    product_detected_from = info.release_source or "Configuration.xml"
    release_is_standard_index = effective_mode in {"configuration", "standard"}

    objects = []
    aliases = []
    fields = []
    forms = []
    templates = []
    modules = []
    methods = []
    queries = []
    relations = []

    for xml_path in iter_top_level_metadata_xml(src_root):
        try:
            parsed = parse_object_xml(src_root, xml_path, snapshot_id, effective_mode)
        except Exception as exc:
            relations.append(
                {
                    "id": entity_hash_id(f"{snapshot_id}:parse_error", safe_rel(xml_path, src_root)),
                    "snapshot_id": snapshot_id,
                    "source_type": "file",
                    "source_id": None,
                    "source_full_name": safe_rel(xml_path, src_root),
                    "relation_type": "parse_error",
                    "target_type": "error",
                    "target_id": None,
                    "target_full_name": str(exc),
                    "confidence": 1,
                    "source_location": {"path": safe_rel(xml_path, src_root)},
                    "metadata": {},
                }
            )
            continue
        objects.append(parsed["object"])
        aliases.extend(parsed["aliases"])
        fields.extend(parsed["fields"])
        forms.extend(parsed["forms"])
        templates.extend(parsed["templates"])

    object_by_key = {(obj["object_type"], obj["name"]): obj for obj in objects}
    for obj in objects:
        obj_modules, obj_methods, obj_queries, obj_relations = parse_modules_for_object(
            src_root, obj, snapshot_id, include_code_text=options.include_code_text
        )
        modules.extend(obj_modules)
        methods.extend(obj_methods)
        queries.extend(obj_queries)
        relations.extend(obj_relations)

    relations.extend(extract_field_type_relations(fields, snapshot_id))
    files = build_files(src_root, snapshot_id, objects, forms, templates, modules)
    cards = build_cards(snapshot_id, objects, fields, forms, templates, modules, methods, queries, info, effective_mode)

    return {
        "schema_version": SCHEMA_VERSION,
        "indexer_version": __version__,
        "source_info": source_info_to_dict(info),
        "configuration_products": [
            {
                "id": product_code,
                "code": product_code,
                "name": release_synonym or release_internal_name or product_code,
                "internal_name": release_internal_name,
                "short_name": product_code.upper(),
                "vendor": release_vendor,
                "description": "",
                "status": "active",
                "metadata": {"detected_from": product_detected_from, "base_source_path": info.base_source_path},
            }
        ],
        "configuration_product_releases": [
            {
                "id": f"{product_code}:{release_version}",
                "product_id": product_code,
                "version": release_version,
                "internal_name": release_internal_name,
                "synonym": release_synonym,
                "vendor": release_vendor,
                "compatibility_mode": release_compatibility_mode,
                "extension_compatibility_mode": "" if info.base_source_path else info.extension_compatibility_mode,
                "standard_snapshot_id": snapshot_id if release_is_standard_index else None,
                "index_status": "completed" if release_is_standard_index else "pending",
                "metadata": {
                    "source_kind": effective_mode,
                    "release_source": info.release_source,
                    "base_source_path": info.base_source_path,
                    "reference_only": not release_is_standard_index,
                },
            }
        ],
        "configuration_snapshots": [
            {
                "id": snapshot_id,
                "product_id": product_code,
                "release_id": f"{product_code}:{release_version}",
                "version": release_version,
                "scope": snapshot_scope(effective_mode),
                "platform_version": "",
                "source_path": str(src_root),
                "source_kind": effective_mode,
                "extension_name": info.name if effective_mode == "extension" else "",
                "description": f"Indexed by configuration-indexer {__version__}",
                "status": "active",
                "indexed_at": datetime.now().isoformat(timespec="seconds"),
                "metadata": {"source_info": source_info_to_dict(info)},
            }
        ],
        "configuration_index_runs": [
            {
                "id": f"{snapshot_id}:run:{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "snapshot_id": snapshot_id,
                "status": "completed",
                "source_path": str(src_root),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "stats": {},
                "error_text": None,
            }
        ],
        "configuration_files": files,
        "configuration_objects": objects,
        "configuration_aliases": aliases,
        "configuration_object_fields": fields,
        "configuration_forms": forms,
        "configuration_templates": templates,
        "configuration_modules": modules,
        "configuration_methods": methods,
        "configuration_queries": queries,
        "configuration_relations": relations,
        "configuration_cards": cards,
        "summary": {
            "source_kind": effective_mode,
            "snapshot_id": snapshot_id,
            "product_code": product_code,
            "release_version": release_version,
            "release_source": info.release_source,
            "objects": len(objects),
            "aliases": len(aliases),
            "fields": len(fields),
            "forms": len(forms),
            "templates": len(templates),
            "modules": len(modules),
            "methods": len(methods),
            "queries": len(queries),
            "relations": len(relations),
            "cards": len(cards),
            "files": len(files),
        },
    }


def snapshot_scope(mode: str) -> str:
    if mode == "extension":
        return "extension"
    if mode in {"client_base", "main_override"}:
        return "client_base"
    if mode == "external":
        return "external"
    return "standard"


def iter_top_level_metadata_xml(src_root: Path):
    ignored = {"Ext"}
    for folder in sorted(p for p in src_root.iterdir() if p.is_dir() and p.name not in ignored):
        for xml_path in sorted(folder.glob("*.xml")):
            yield xml_path


def parse_object_xml(src_root: Path, xml_path: Path, snapshot_id: str, source_kind: str) -> dict:
    root = read_xml(xml_path)
    node = first_metadata_node(root)
    if node is None:
        raise ValueError("metadata node not found")
    object_type = local_name(node.tag)
    properties = props(node)
    name = child_text(properties, "Name") or xml_path.stem
    full_name = f"{object_type}.{name}"
    oid = object_id(snapshot_id, object_type, name)
    synonym = localized_text(properties, "Synonym")
    comment = child_text(properties, "Comment")
    object_belonging = child_text(properties, "ObjectBelonging")
    extended_object = child_text(properties, "ExtendedConfigurationObject")

    obj = {
        "id": oid,
        "snapshot_id": snapshot_id,
        "object_type": object_type,
        "name": name,
        "full_name": full_name,
        "synonym": synonym,
        "comment": comment,
        "parent_object_id": None,
        "xml_path": safe_rel(xml_path, src_root),
        "help_path": "",
        "is_standard": source_kind not in {"extension", "client_base", "main_override"},
        "file_hash": sha1_file(xml_path),
        "metadata": {
            "uuid": node.attrib.get("uuid", ""),
            "object_belonging": object_belonging,
            "extended_configuration_object": extended_object,
            "extension_object_kind": extension_object_kind(source_kind, object_belonging, extended_object),
        },
    }

    aliases = []
    aliases.extend(make_aliases(snapshot_id, oid, "object", oid, name, synonym, full_name))
    fields = []
    forms = []
    templates = []
    position = 0
    child_objects = child(node, "ChildObjects")
    for child_node in children(child_objects):
        child_kind = local_name(child_node.tag)
        if child_kind == "Attribute":
            position += 1
            field = parse_attribute(snapshot_id, oid, full_name, child_node, None, "attribute", position)
            fields.append(field)
            aliases.extend(make_aliases(snapshot_id, oid, "field", field["id"], field["name"], field.get("synonym", ""), field["full_name"]))
        elif child_kind == "TabularSection":
            position += 1
            table_props = props(child_node)
            table_name = child_text(table_props, "Name")
            table_synonym = localized_text(table_props, "Synonym")
            table_full = f"{full_name}.{table_name}"
            table_id = f"{oid}:field:{table_full}"
            table_field = {
                "id": table_id,
                "snapshot_id": snapshot_id,
                "object_id": oid,
                "field_kind": "tabular_section",
                "table_part_name": None,
                "name": table_name,
                "full_name": table_full,
                "synonym": table_synonym,
                "value_type": "",
                "path": table_full,
                "position": position,
                "metadata": {"uuid": child_node.attrib.get("uuid", "")},
            }
            fields.append(table_field)
            aliases.extend(make_aliases(snapshot_id, oid, "field", table_id, table_name, table_synonym, table_full))
            nested_position = 0
            for nested_node in children(child(child_node, "ChildObjects"), "Attribute"):
                nested_position += 1
                field = parse_attribute(snapshot_id, oid, full_name, nested_node, table_name, "table_part_field", nested_position)
                fields.append(field)
                aliases.extend(make_aliases(snapshot_id, oid, "field", field["id"], field["name"], field.get("synonym", ""), field["full_name"]))
        elif child_kind == "Form" and child_node.text:
            form = make_form(src_root, snapshot_id, oid, object_type, name, child_node.text.strip())
            forms.append(form)
            aliases.extend(make_aliases(snapshot_id, oid, "form", form["id"], form["name"], form.get("synonym", ""), form["full_name"]))
        elif child_kind == "Template" and child_node.text:
            template = make_template(src_root, snapshot_id, oid, object_type, name, child_node.text.strip())
            templates.append(template)
            aliases.extend(
                make_aliases(snapshot_id, oid, "template", template["id"], template["name"], template.get("synonym", ""), template["full_name"])
            )

    return {"object": obj, "aliases": aliases, "fields": fields, "forms": forms, "templates": templates}


def extension_object_kind(source_kind: str, object_belonging: str, extended_object: str) -> str:
    if source_kind != "extension":
        return ""
    if object_belonging == "Adopted" or extended_object:
        return "adopted"
    return "own"


def make_aliases(snapshot_id: str, object_identifier: str, entity_type: str, entity_id: str, name: str, synonym: str, source_path: str):
    aliases = []
    if name:
        aliases.append(
            {
                "id": f"{entity_id}:alias:metadata_name:{sha1_text(name)[:10]}",
                "snapshot_id": snapshot_id,
                "object_id": object_identifier,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "alias_type": "metadata_name",
                "alias": name,
                "source": "indexer",
                "confidence": 1.0,
                "status": "active",
                "metadata": {"from": source_path},
            }
        )
    if synonym and synonym != name:
        aliases.append(
            {
                "id": f"{entity_id}:alias:synonym:{sha1_text(synonym)[:10]}",
                "snapshot_id": snapshot_id,
                "object_id": object_identifier,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "alias_type": "synonym",
                "alias": synonym,
                "source": "indexer",
                "confidence": 0.9,
                "status": "active",
                "metadata": {"from": source_path},
            }
        )
    return aliases


def parse_attribute(snapshot_id: str, oid: str, object_full_name: str, node, table_name: str | None, field_kind: str, position: int) -> dict:
    properties = props(node)
    name = child_text(properties, "Name")
    synonym = localized_text(properties, "Synonym")
    full = f"{object_full_name}.{table_name}.{name}" if table_name else f"{object_full_name}.{name}"
    return {
        "id": f"{oid}:field:{full}",
        "snapshot_id": snapshot_id,
        "object_id": oid,
        "field_kind": field_kind,
        "table_part_name": table_name,
        "name": name,
        "full_name": full,
        "synonym": synonym,
        "value_type": type_text(properties),
        "path": full,
        "position": position,
        "metadata": {
            "uuid": node.attrib.get("uuid", ""),
            "object_belonging": child_text(properties, "ObjectBelonging"),
            "extended_configuration_object": child_text(properties, "ExtendedConfigurationObject"),
            "tooltip": localized_text(properties, "ToolTip"),
            "fill_checking": child_text(properties, "FillChecking"),
            "use": child_text(properties, "Use"),
            "indexing": child_text(properties, "Indexing"),
        },
    }


def make_form(src_root: Path, snapshot_id: str, oid: str, object_type: str, object_name: str, form_name: str) -> dict:
    object_dir = src_root / f"{object_type}s" / object_name
    if not object_dir.exists():
        object_dir = next((p for p in src_root.iterdir() if p.is_dir() and (p / object_name).exists()), src_root) / object_name
    form_meta = object_dir / "Forms" / f"{form_name}.xml"
    form_ext = object_dir / "Forms" / form_name / "Ext" / "Form.xml"
    module_path = object_dir / "Forms" / form_name / "Ext" / "Form" / "Module.bsl"
    synonym = ""
    form_kind = ""
    if form_meta.exists():
        try:
            root = read_xml(form_meta)
            form_node = first_metadata_node(root)
            properties = props(form_node)
            synonym = localized_text(properties, "Synonym")
            form_kind = child_text(properties, "FormType") or child_text(properties, "Type")
        except Exception:
            pass
    return {
        "id": f"{oid}:form:{form_name}",
        "snapshot_id": snapshot_id,
        "object_id": oid,
        "name": form_name,
        "full_name": f"{object_type}.{object_name}.Form.{form_name}",
        "synonym": synonym,
        "form_kind": form_kind,
        "xml_path": safe_rel(form_ext, src_root) if form_ext.exists() else safe_rel(form_meta, src_root) if form_meta.exists() else "",
        "module_path": safe_rel(module_path, src_root) if module_path.exists() else "",
        "file_hash": sha1_file(form_ext) if form_ext.exists() else sha1_file(form_meta) if form_meta.exists() else "",
        "metadata": {},
    }


def make_template(src_root: Path, snapshot_id: str, oid: str, object_type: str, object_name: str, template_name: str) -> dict:
    object_dir = src_root / f"{object_type}s" / object_name
    template_meta = object_dir / "Templates" / f"{template_name}.xml"
    template_ext = object_dir / "Templates" / template_name / "Ext" / "Template.xml"
    return {
        "id": f"{oid}:template:{template_name}",
        "snapshot_id": snapshot_id,
        "object_id": oid,
        "name": template_name,
        "full_name": f"{object_type}.{object_name}.Template.{template_name}",
        "synonym": "",
        "template_kind": "",
        "path": safe_rel(template_ext, src_root) if template_ext.exists() else safe_rel(template_meta, src_root) if template_meta.exists() else "",
        "file_hash": sha1_file(template_ext) if template_ext.exists() else sha1_file(template_meta) if template_meta.exists() else "",
        "metadata": {},
    }


def parse_modules_for_object(src_root: Path, obj: dict, snapshot_id: str, include_code_text: bool = True):
    xml_path = src_root / obj["xml_path"]
    object_dir = xml_path.with_suffix("")
    modules = []
    methods = []
    queries = []
    relations = []
    if not object_dir.exists():
        return modules, methods, queries, relations
    for path in sorted(object_dir.rglob("*.bsl")):
        rel = safe_rel(path, src_root)
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        module_kind, module_name, form_name = module_kind_from_path(path, object_dir)
        mid = f"{obj['id']}:module:{rel}"
        modules.append(
            {
                "id": mid,
                "snapshot_id": snapshot_id,
                "object_id": obj["id"],
                "form_id": f"{obj['id']}:form:{form_name}" if form_name else None,
                "module_kind": module_kind,
                "name": module_name,
                "full_name": f"{obj['full_name']}.{module_name}",
                "path": rel,
                "file_hash": sha1_file(path),
                "code_hash": sha1_text(text),
                "code_text": text if include_code_text and len(text) <= 120_000 else "",
                "metadata": {"lines": len(text.splitlines())},
            }
        )
        for method in parse_bsl_methods(text):
            met_id = f"{mid}:method:{method['name']}:{method['start_line']}"
            method_full = f"{obj['full_name']}.{module_name}.{method['name']}"
            methods.append(
                {
                    "id": met_id,
                    "snapshot_id": snapshot_id,
                    "object_id": obj["id"],
                    "module_id": mid,
                    "name": method["name"],
                    "full_name": method_full,
                    "is_function": method["is_function"],
                    "is_export": method["is_export"],
                    "signature": method["signature"],
                    "parameters": method["parameters"],
                    "return_type": "",
                    "start_line": method["start_line"],
                    "end_line": method["end_line"],
                    "body_hash": method["body_hash"],
                    "body_text": method["body_text"] if include_code_text else "",
                    "metadata": {"annotations": method["annotations"], "module_path": rel},
                }
            )
            for query_index, query_text in enumerate(extract_queries(method["body_text"])):
                qid = f"{met_id}:query:{query_index}"
                queries.append(
                    {
                        "id": qid,
                        "snapshot_id": snapshot_id,
                        "object_id": obj["id"],
                        "module_id": mid,
                        "method_id": met_id,
                        "query_kind": "bsl_string_detected",
                        "name": f"{method['name']}#{query_index + 1}",
                        "full_name": f"{method_full}.Query.{query_index + 1}",
                        "query_text": query_text,
                        "normalized_text": normalize_query(query_text),
                        "path": rel,
                        "start_line": method["start_line"],
                        "end_line": method["end_line"],
                        "query_hash": sha1_text(query_text),
                        "metadata": {},
                    }
                )
            relations.extend(extract_relations(met_id, method_full, method["body_text"], rel, method["start_line"], snapshot_id))
    return modules, methods, queries, relations


def module_kind_from_path(path: Path, object_dir: Path):
    parts = path.relative_to(object_dir).parts
    if path.name == "ObjectModule.bsl":
        return "ObjectModule", "ObjectModule", None
    if path.name == "ManagerModule.bsl":
        return "ManagerModule", "ManagerModule", None
    if path.name == "RecordSetModule.bsl":
        return "RecordSetModule", "RecordSetModule", None
    if len(parts) >= 4 and parts[0] == "Forms":
        return "FormModule", f"Form.{parts[1]}.Module", parts[1]
    if len(parts) >= 4 and parts[0] == "Commands":
        return "CommandModule", f"Command.{parts[1]}.Module", None
    if len(parts) >= 3 and parts[0] == "Ext":
        return "Module", "Module", None
    return "Module", path.stem, None


def extract_field_type_relations(fields: list[dict], snapshot_id: str):
    relations = []
    seen = set()
    for field in fields:
        value_type = field.get("value_type") or ""
        for target_type, pattern in TYPE_REF_PATTERNS:
            for match in pattern.finditer(value_type):
                target_name = match.group(1)
                target_full = f"{target_type}.{target_name}"
                key = (field["id"], target_type, target_full)
                if key in seen:
                    continue
                seen.add(key)
                relations.append(
                    {
                        "id": f"{field['id']}:rel:field_value_type:{sha1_text(target_full)[:12]}",
                        "snapshot_id": snapshot_id,
                        "source_type": "field",
                        "source_id": field["id"],
                        "source_full_name": field["full_name"],
                        "relation_type": "field_value_type",
                        "target_type": target_type,
                        "target_id": None,
                        "target_full_name": target_full,
                        "confidence": 0.95,
                        "source_location": {"path": field["path"]},
                        "metadata": {"detected_by": "xml_type", "value_type": value_type},
                    }
                )
    return relations


def build_files(src_root: Path, snapshot_id: str, objects, forms, templates, modules) -> list[dict]:
    files = []
    paths: set[str] = set()
    for obj in objects:
        for key in ("xml_path", "help_path"):
            value = obj.get(key)
            if value:
                paths.add(value)
    for form in forms:
        for key in ("xml_path", "module_path"):
            value = form.get(key)
            if value:
                paths.add(value)
    for template in templates:
        value = template.get("path")
        if value:
            paths.add(value)
    for module in modules:
        value = module.get("path")
        if value:
            paths.add(value)

    for rel_path in sorted(paths):
        path = src_root / rel_path
        if not path.is_file():
            continue
        rel = safe_rel(path, src_root)
        files.append(
            {
                "id": f"{snapshot_id}:file:{rel}",
                "snapshot_id": snapshot_id,
                "path": rel,
                "file_kind": path.suffix.lower().lstrip("."),
                "file_hash": sha1_file(path),
                "size_bytes": path.stat().st_size,
                "entity_type": "",
                "entity_id": "",
                "parsed_at": None,
                "metadata": {},
            }
        )
    return files


def build_cards(snapshot_id: str, objects, fields, forms, templates, modules, methods, queries, info: SourceInfo, source_kind: str):
    cards = []
    fields_by_object = group_by_object(fields)
    forms_by_object = group_by_object(forms)
    templates_by_object = group_by_object(templates)
    modules_by_object = group_by_object(modules)
    methods_by_object = group_by_object(methods)
    queries_by_object = group_by_object(queries)

    for obj in objects:
        obj_fields = fields_by_object.get(obj["id"], [])
        obj_forms = forms_by_object.get(obj["id"], [])
        obj_templates = templates_by_object.get(obj["id"], [])
        obj_modules = modules_by_object.get(obj["id"], [])
        obj_methods = methods_by_object.get(obj["id"], [])
        obj_queries = queries_by_object.get(obj["id"], [])
        attrs = [f for f in obj_fields if f["field_kind"] == "attribute"]
        tabs = [f for f in obj_fields if f["field_kind"] == "tabular_section"]
        exported = [m for m in obj_methods if m["is_export"]]
        text = "\n".join(
            [
                f"Источник: {source_kind}",
                f"Конфигурация: {info.synonym or info.name}",
                f"Объект: {obj['full_name']}",
                f"Синоним: {obj.get('synonym') or ''}",
                f"Комментарий: {obj.get('comment') or ''}",
                f"Принадлежность расширения: {obj['metadata'].get('extension_object_kind') or ''}",
                "",
                "Реквизиты: " + ", ".join(f"{f['name']} ({f.get('value_type') or 'тип не извлечён'})" for f in attrs[:30]),
                "Табличные части: " + ", ".join(f["name"] for f in tabs),
                "Формы: " + ", ".join(f["name"] for f in obj_forms),
                "Макеты: " + ", ".join(t["name"] for t in obj_templates),
                "Модули: " + ", ".join(f"{m['module_kind']}:{m['name']}" for m in obj_modules),
                "Экспортные методы: " + ", ".join(m["name"] for m in exported[:30]),
                f"Найдено методов: {len(obj_methods)}",
                f"Найдено запросов: {len(obj_queries)}",
            ]
        )
        cards.append(
            {
                "id": f"{obj['id']}:card:object_summary",
                "snapshot_id": snapshot_id,
                "object_id": obj["id"],
                "module_id": None,
                "method_id": None,
                "query_id": None,
                "card_type": "object_summary",
                "title": f"{obj['object_type']} {obj['name']}: структура и код",
                "text": text,
                "source": "indexer",
                "status": "draft",
                "confidence": 0.75,
                "metadata": {"source_kind": source_kind},
            }
        )
    return cards


def group_by_object(rows) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        object_identifier = row.get("object_id")
        if object_identifier:
            grouped[object_identifier].append(row)
    return grouped


def write_outputs(index: dict, out_json: Path, out_summary: Path | None = None) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_summary:
        out_summary.parent.mkdir(parents=True, exist_ok=True)
        out_summary.write_text(render_summary(index), encoding="utf-8")


def render_summary(index: dict) -> str:
    if "project_info" in index:
        return render_project_summary(index)

    info = index["source_info"]
    lines = ["# 1C Configuration Index", "", "## Source", ""]
    lines.append(f"- root: {info['root']}")
    lines.append(f"- source_kind: {index['summary']['source_kind']}")
    lines.append(f"- name: {info.get('name') or ''}")
    lines.append(f"- synonym: {info.get('synonym') or ''}")
    lines.append(f"- version: {info.get('version') or ''}")
    lines.append(f"- extension_purpose: {info.get('extension_purpose') or ''}")
    lines.append(f"- markers: {', '.join(info.get('markers') or [])}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in index["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## First Objects")
    for obj in index["configuration_objects"][:40]:
        obj_methods = [m for m in index["configuration_methods"] if m["object_id"] == obj["id"]]
        obj_fields = [f for f in index["configuration_object_fields"] if f["object_id"] == obj["id"]]
        lines.append("")
        lines.append(f"### {obj['full_name']}")
        lines.append(f"- synonym: {obj.get('synonym') or ''}")
        lines.append(f"- extension_object_kind: {obj['metadata'].get('extension_object_kind') or ''}")
        lines.append(f"- fields: {len(obj_fields)}")
        lines.append(f"- methods: {len(obj_methods)}")
    return "\n".join(lines)


def render_project_summary(index: dict) -> str:
    info = index["project_info"]
    lines = ["# 1C Configuration Project Index", "", "## Project", ""]
    lines.append(f"- root: {info.get('root') or ''}")
    lines.append(f"- base_profile_id: {info.get('base_profile_id') or ''}")
    lines.append(f"- product_code: {info.get('product_code') or ''}")
    lines.append(f"- release_version: {info.get('release_version') or ''}")
    lines.append(f"- standard_snapshot_id: {info.get('standard_snapshot_id') or ''}")
    lines.append(f"- manifest_path: {info.get('manifest_path') or ''}")
    lines.append("")
    lines.append("## Layers")
    for layer in index.get("configuration_snapshot_layers", []):
        lines.append("")
        lines.append(f"- order: {layer.get('layer_order')}")
        lines.append(f"  kind: {layer.get('layer_kind')}")
        lines.append(f"  snapshot_id: {layer.get('layer_snapshot_id')}")
        if layer.get("extension_name"):
            lines.append(f"  extension_name: {layer.get('extension_name')}")
    lines.append("")
    lines.append("## Extensions")
    extensions = info.get("extensions") or []
    if not extensions:
        lines.append("- none")
    for extension in extensions:
        summary = extension.get("summary") or {}
        lines.append("")
        lines.append(f"### {extension.get('name') or extension.get('relative_path')}")
        lines.append(f"- path: {extension.get('relative_path') or extension.get('path')}")
        lines.append(f"- snapshot_id: {extension.get('snapshot_id')}")
        lines.append(f"- objects: {summary.get('objects', 0)}")
        lines.append(f"- modules: {summary.get('modules', 0)}")
        lines.append(f"- methods: {summary.get('methods', 0)}")
        lines.append(f"- queries: {summary.get('queries', 0)}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in index["summary"].items():
        lines.append(f"- {key}: {value}")
    warnings = info.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)
