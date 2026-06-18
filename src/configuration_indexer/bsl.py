from __future__ import annotations

import re

from .xml_utils import sha1_text


METHOD_RE = re.compile(
    r"(?m)^(?P<kind>Процедура|Функция)\s+(?P<name>[A-Za-zА-Яа-яЁё0-9_]+)\s*\((?P<params>[^)]*)\)\s*(?P<tail>.*)$"
)

SOURCE_PATTERNS = [
    ("Catalog", re.compile(r"(?:Справочники|Справочник|Метаданные\.Справочники)\.([A-Za-zА-Яа-яЁё0-9_]+)")),
    ("Document", re.compile(r"(?:Документы|Документ|Метаданные\.Документы)\.([A-Za-zА-Яа-яЁё0-9_]+)")),
    (
        "InformationRegister",
        re.compile(r"(?:РегистрыСведений|РегистрСведений|Метаданные\.РегистрыСведений)\.([A-Za-zА-Яа-яЁё0-9_]+)"),
    ),
    (
        "AccumulationRegister",
        re.compile(r"(?:РегистрыНакопления|РегистрНакопления|Метаданные\.РегистрыНакопления)\.([A-Za-zА-Яа-яЁё0-9_]+)"),
    ),
    ("CommonModule", re.compile(r"(?:ОбщиеМодули|Метаданные\.ОбщиеМодули)\.([A-Za-zА-Яа-яЁё0-9_]+)")),
]


def parse_bsl_methods(text: str) -> list[dict]:
    lines = text.splitlines()
    matches = list(METHOD_RE.finditer(text))
    methods = []
    for index, match in enumerate(matches):
        start_offset = match.start()
        end_offset = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        start_line = text[:start_offset].count("\n") + 1
        end_line = text[:end_offset].count("\n") + 1
        body = text[start_offset:end_offset].rstrip()
        annotations = []
        line_idx = start_line - 2
        while line_idx >= 0:
            value = lines[line_idx].strip()
            if not value:
                line_idx -= 1
                continue
            if value.startswith("&"):
                annotations.insert(0, value)
                line_idx -= 1
                continue
            break
        params = [
            {"name": part.strip().split("=")[0].strip(), "raw": part.strip()}
            for part in match.group("params").split(",")
            if part.strip()
        ]
        methods.append(
            {
                "kind": match.group("kind"),
                "name": match.group("name"),
                "parameters": params,
                "is_function": match.group("kind") == "Функция",
                "is_export": "Экспорт" in match.group("tail"),
                "signature": match.group(0).strip(),
                "annotations": annotations,
                "start_line": start_line,
                "end_line": end_line,
                "body_text": body,
                "body_hash": sha1_text(body),
            }
        )
    return methods


def extract_queries(body: str) -> list[str]:
    if "ВЫБРАТЬ" not in body.upper():
        return []
    lines = body.splitlines()
    result = []
    for i, line in enumerate(lines):
        if "ВЫБРАТЬ" not in line.upper():
            continue
        chunk = []
        for raw in lines[i : min(i + 100, len(lines))]:
            stripped = raw.strip()
            if stripped.startswith("|"):
                stripped = stripped[1:]
            stripped = stripped.strip().strip('";')
            if stripped:
                chunk.append(stripped)
            if raw.strip().endswith('";') and len(chunk) > 1:
                break
        query = "\n".join(chunk)
        if query and query not in result:
            result.append(query)
    return result


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("|", " ")).strip()


def extract_relations(method_identifier: str, method_full_name: str, body: str, path: str, start_line: int, snapshot_id: str):
    relations = []
    seen = set()
    for target_type, pattern in SOURCE_PATTERNS:
        for match in pattern.finditer(body):
            target_name = match.group(1)
            target_full = f"{target_type}.{target_name}"
            key = (target_type, target_full)
            if key in seen:
                continue
            seen.add(key)
            relations.append(
                {
                    "id": f"{method_identifier}:rel:uses_metadata_object:{sha1_text(target_full)[:12]}",
                    "snapshot_id": snapshot_id,
                    "source_type": "method",
                    "source_id": method_identifier,
                    "source_full_name": method_full_name,
                    "relation_type": "uses_metadata_object",
                    "target_type": target_type,
                    "target_id": None,
                    "target_full_name": target_full,
                    "confidence": 0.85,
                    "source_location": {"path": path, "method_start_line": start_line},
                    "metadata": {"detected_by": "regex"},
                }
            )
    return relations
