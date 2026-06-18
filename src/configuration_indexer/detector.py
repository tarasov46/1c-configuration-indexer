from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .xml_utils import child_text, first_metadata_node, localized_text, props, read_xml


@dataclass
class SourceInfo:
    root: Path
    is_valid: bool
    source_kind: str
    confidence: float
    name: str = ""
    synonym: str = ""
    version: str = ""
    vendor: str = ""
    compatibility_mode: str = ""
    extension_compatibility_mode: str = ""
    extension_purpose: str = ""
    keep_mapping: str = ""
    name_prefix: str = ""
    root_object_belonging: str = ""
    metadata_xml_version: str = ""
    product_code: str = ""
    release_version: str = ""
    release_source: str = ""
    base_source_path: str = ""
    base_name: str = ""
    base_synonym: str = ""
    base_version: str = ""
    base_vendor: str = ""
    base_compatibility_mode: str = ""
    markers: list[str] = field(default_factory=list)
    error: str = ""


def detect_source(root: Path, resolve_base_hint: bool = True) -> SourceInfo:
    root = Path(root)
    configuration_xml = root / "Configuration.xml"
    if not configuration_xml.exists():
        return SourceInfo(
            root=root,
            is_valid=False,
            source_kind="unknown",
            confidence=0,
            error="Configuration.xml not found",
        )

    try:
        xml_root = read_xml(configuration_xml)
        metadata_xml_version = xml_root.attrib.get("version", "")
        configuration_node = first_metadata_node(xml_root)
        if configuration_node is None:
            raise ValueError("metadata node not found")
        properties = props(configuration_node)
        name = child_text(properties, "Name")
        synonym = localized_text(properties, "Synonym")
        version = child_text(properties, "Version")
        vendor = child_text(properties, "Vendor")
        compatibility_mode = child_text(properties, "CompatibilityMode")
        extension_compatibility_mode = child_text(properties, "ConfigurationExtensionCompatibilityMode")
        extension_purpose = child_text(properties, "ConfigurationExtensionPurpose")
        keep_mapping = child_text(properties, "KeepMappingToExtendedConfigurationObjectsByIDs")
        name_prefix = child_text(properties, "NamePrefix")
        object_belonging = child_text(properties, "ObjectBelonging")
    except Exception as exc:
        return SourceInfo(
            root=root,
            is_valid=False,
            source_kind="unknown",
            confidence=0,
            error=f"Cannot parse Configuration.xml: {exc}",
        )

    markers = []
    if extension_purpose:
        markers.append("ConfigurationExtensionPurpose")
    if keep_mapping:
        markers.append("KeepMappingToExtendedConfigurationObjectsByIDs")
    if object_belonging:
        markers.append("ObjectBelonging")
    if name_prefix:
        markers.append("NamePrefix")

    if extension_purpose or keep_mapping:
        source_kind = "extension"
        confidence = 0.98
    elif object_belonging == "Adopted":
        source_kind = "extension"
        confidence = 0.9
    else:
        source_kind = "configuration"
        confidence = 0.9

    product_code = ""
    release_version = ""
    release_source = ""
    base_source_path = ""
    base_name = ""
    base_synonym = ""
    base_version = ""
    base_vendor = ""
    base_compatibility_mode = ""
    if source_kind == "configuration":
        product_code = infer_product_code(name, synonym)
        release_version = version
        release_source = "Configuration.Properties.Version" if version else ""
    elif source_kind == "extension" and resolve_base_hint:
        base_info = find_adjacent_base_configuration(root)
        if base_info is not None:
            product_code = base_info.product_code
            release_version = base_info.release_version
            release_source = f"sibling:{base_info.root.name}/Configuration.xml" if release_version else ""
            base_source_path = str(base_info.root)
            base_name = base_info.name
            base_synonym = base_info.synonym
            base_version = base_info.version
            base_vendor = base_info.vendor
            base_compatibility_mode = base_info.compatibility_mode
            markers.append("SiblingBaseConfiguration")

    return SourceInfo(
        root=root,
        is_valid=True,
        source_kind=source_kind,
        confidence=confidence,
        name=name,
        synonym=synonym,
        version=version,
        vendor=vendor,
        compatibility_mode=compatibility_mode,
        extension_compatibility_mode=extension_compatibility_mode,
        extension_purpose=extension_purpose,
        keep_mapping=keep_mapping,
        name_prefix=name_prefix,
        root_object_belonging=object_belonging,
        metadata_xml_version=metadata_xml_version,
        product_code=product_code,
        release_version=release_version,
        release_source=release_source,
        base_source_path=base_source_path,
        base_name=base_name,
        base_synonym=base_synonym,
        base_version=base_version,
        base_vendor=base_vendor,
        base_compatibility_mode=base_compatibility_mode,
        markers=markers,
    )


def find_adjacent_base_configuration(root: Path) -> SourceInfo | None:
    parent = root.parent
    candidates: list[Path] = []
    for preferred in (parent / "src", parent.parent / "src"):
        if preferred.exists() and preferred.is_dir() and not same_path(preferred, root):
            candidates.append(preferred)

    try:
        siblings = sorted(parent.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        siblings = []

    for sibling in siblings:
        if not sibling.is_dir() or same_path(sibling, root) or sibling in candidates:
            continue
        if not (sibling / "Configuration.xml").exists():
            continue
        if sibling.name.lower().startswith("src"):
            candidates.append(sibling)

    for candidate in candidates:
        info = detect_source(candidate, resolve_base_hint=False)
        if info.is_valid and info.source_kind == "configuration" and (info.product_code or info.release_version):
            return info
    return None


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def infer_product_code(name: str, synonym: str) -> str:
    text = f"{name} {synonym}".lower()
    compact = text.replace(" ", "").replace(":", "")
    if "управлениепредприятием" in compact or "erp" in text:
        return "erp"
    if "управлениеторговлей" in compact or "ут" in text or "trade management" in text:
        return "ut"
    if "комплекснаяавтоматизация" in compact or "ка" in text:
        return "ka"
    if "бухгалтерияпредприятия" in compact or "бп" in text or "бухгалтерия" in text:
        return "bp"
    if "зарплатаиуправлениеперсоналом" in compact or "зуп" in text or "зарплата" in text:
        return "zup"
    return name.lower() if name else ""


def source_info_to_dict(info: SourceInfo) -> dict:
    return {
        "root": str(info.root),
        "is_valid": info.is_valid,
        "source_kind": info.source_kind,
        "confidence": info.confidence,
        "name": info.name,
        "synonym": info.synonym,
        "version": info.version,
        "vendor": info.vendor,
        "compatibility_mode": info.compatibility_mode,
        "extension_compatibility_mode": info.extension_compatibility_mode,
        "extension_purpose": info.extension_purpose,
        "keep_mapping": info.keep_mapping,
        "name_prefix": info.name_prefix,
        "root_object_belonging": info.root_object_belonging,
        "metadata_xml_version": info.metadata_xml_version,
        "product_code": info.product_code,
        "release_version": info.release_version,
        "release_source": info.release_source,
        "base_source_path": info.base_source_path,
        "base_name": info.base_name,
        "base_synonym": info.base_synonym,
        "base_version": info.base_version,
        "base_vendor": info.base_vendor,
        "base_compatibility_mode": info.base_compatibility_mode,
        "markers": info.markers,
        "error": info.error,
    }
