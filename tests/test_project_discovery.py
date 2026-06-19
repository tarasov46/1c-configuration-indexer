from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from configuration_indexer.project import detect_project


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
    def test_detects_extensions_from_exchanges_and_skips_sibling_duplicate(self) -> None:
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
        self.assertTrue(any("Skipped duplicate extension src exchange" in warning for warning in layout.warnings))


def write_config(path: Path, content: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "Configuration.xml").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
