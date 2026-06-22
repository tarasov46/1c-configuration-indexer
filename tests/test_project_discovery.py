from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from configuration_indexer.project import ProjectIndexOptions, detect_project, parse_project


BASE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject version="2.20">
  <Configuration uuid="base">
    <Properties>
      <Name>УправлениеПредприятием</Name>
      <Synonym><item><lang>ru</lang><content>1С:ERP Управление предприятием 2</content></item></Synonym>
      <Version>2.5.27.47</Version>
    </Properties>
  </Configuration>
</MetaDataObject>
"""


def extension_xml(name: str, version: str = "Version8_3_21") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject version="2.20">
  <Configuration uuid="{name}">
    <Properties>
      <Name>{name}</Name>
      <Synonym><item><lang>ru</lang><content>{name}</content></item></Synonym>
      <ConfigurationExtensionCompatibilityMode>{version}</ConfigurationExtensionCompatibilityMode>
      <ConfigurationExtensionPurpose>Customization</ConfigurationExtensionPurpose>
    </Properties>
  </Configuration>
</MetaDataObject>
"""


class ProjectDiscoveryTests(unittest.TestCase):
    def test_detects_src_and_exchanges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_config(root / "src", BASE_XML)
            write_config(root / "exchanges" / "ExtA", extension_xml("ExtA"))
            write_config(root / "exchanges" / "ExtB", extension_xml("ExtB"))
            write_config(root / "src exchange", extension_xml("ExtA"))

            layout = detect_project(root)

        self.assertTrue(layout.is_valid)
        self.assertEqual([entry.name for entry in layout.extensions], ["ExtA", "ExtB"])
        self.assertEqual([entry.source for entry in layout.extensions], ["exchanges", "exchanges"])
        self.assertEqual(layout.warnings, [])

    def test_detects_src_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_config(root / "src", BASE_XML)

            layout = detect_project(root)

        self.assertTrue(layout.is_valid)
        self.assertIsNotNone(layout.base_src)
        self.assertEqual(layout.extensions, [])

    def test_detects_exchanges_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_config(root / "exchanges" / "ExtA", extension_xml("ExtA"))

            layout = detect_project(root)
            project = parse_project(
                ProjectIndexOptions(
                    project_root=root,
                    base_mode="detect",
                    product_code="erp",
                    release_version="2.5.27.47",
                    standard_snapshot_id="standard:erp:2.5.27.47",
                    client_id="client",
                    base_id="base",
                    include_code_text=False,
                )
            )

        self.assertTrue(layout.is_valid)
        self.assertIsNone(layout.base_src)
        self.assertEqual([entry.name for entry in layout.extensions], ["ExtA"])
        self.assertEqual(project["summary"]["extensions"], 1)
        self.assertEqual(project["summary"]["product_code"], "erp")
        self.assertEqual(project["summary"]["release_version"], "2.5.27.47")
        self.assertEqual(project["project_info"]["layout"], "exchanges")
        self.assertEqual(project["project_info"]["extensions"][0]["snapshot_id"], "extension:client:base:ExtA")

    def test_detects_exchanges_folder_as_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "exchanges"
            write_config(root / "ExtA", extension_xml("ExtA"))

            layout = detect_project(root)

        self.assertTrue(layout.is_valid)
        self.assertIsNone(layout.base_src)
        self.assertEqual([entry.name for entry in layout.extensions], ["ExtA"])


def write_config(path: Path, content: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "Configuration.xml").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
