from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def children(element, name: str | None = None):
    if element is None:
        return []
    if name is None:
        return list(element)
    return [child for child in element if local_name(child.tag) == name]


def child(element, name: str):
    found = children(element, name)
    return found[0] if found else None


def child_text(element, name: str, default: str = "") -> str:
    node = child(element, name)
    return (node.text or "").strip() if node is not None and node.text else default


def props(element):
    return child(element, "Properties")


def read_xml(path: Path):
    return ET.parse(path).getroot()


def localized_text(properties, container_name: str) -> str:
    container = child(properties, container_name)
    if container is None:
        return ""
    first = ""
    for item in children(container):
        lang = child_text(item, "lang")
        content = child_text(item, "content")
        if content and not first:
            first = content
        if lang == "ru" and content:
            return content
    return first


def type_text(properties) -> str:
    type_node = child(properties, "Type")
    if type_node is None:
        return ""
    values = []
    for node in type_node.iter():
        if local_name(node.tag) in {"Type", "TypeSet"} and node.text and node.text.strip():
            values.append(node.text.strip())
    return ", ".join(dict.fromkeys(values))


def first_metadata_node(root):
    for node in children(root):
        if local_name(node.tag) != "InternalInfo":
            return node
    return None


def safe_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def safe_id_part(value: str) -> str:
    return (
        value.replace("\\", "/")
        .replace(" ", "_")
        .replace("\n", "_")
        .replace("\r", "_")
        .strip()
    )
