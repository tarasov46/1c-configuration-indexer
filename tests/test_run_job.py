from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from configuration_indexer.cli import run_job


EXTENSION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject version="2.20">
  <Configuration uuid="ext">
    <Properties>
      <Name>ExtA</Name>
      <Synonym><item><lang>ru</lang><content>ExtA</content></item></Synonym>
      <ConfigurationExtensionCompatibilityMode>Version8_3_21</ConfigurationExtensionCompatibilityMode>
      <ConfigurationExtensionPurpose>Customization</ConfigurationExtensionPurpose>
    </Properties>
  </Configuration>
</MetaDataObject>
"""


class RunJobTests(unittest.TestCase):
    def test_resolves_relative_paths_from_job_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work_dir = root / "work" / "1c-configuration-indexer"
            source_dir = root / "work" / "configuration-src" / "exchanges" / "ExtA"
            source_dir.mkdir(parents=True)
            work_dir.mkdir(parents=True)
            (source_dir / "Configuration.xml").write_text(EXTENSION_XML, encoding="utf-8")

            job_path = work_dir / "indexing-job.json"
            job_path.write_text(
                json.dumps(
                    {
                        "schema_version": "configuration-mcp/indexing-job/2",
                        "job_id": "idx_relative_path",
                        "input": {
                            "source_path": "..\\configuration-src",
                            "base_mode": "detect",
                            "product_code": "erp",
                            "release_version": "2.5.27.47",
                            "standard_snapshot_id": "standard:erp:2.5.27.47",
                            "include_code_text": False,
                        },
                        "profile": {
                            "client_id": "client",
                            "base_id": "base",
                            "base_profile_id": "client:base",
                        },
                        "output": {"out_dir": ".\\out", "package_name": "idx_relative_path"},
                        "upload": {"enabled": False},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_job(job_path, no_upload=True)
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["summary"]["search_chunks"], 0)
        self.assertEqual(result["summary"]["snapshots"], 1)
        self.assertEqual(manifest["snapshot_ids"], ["extension:client:base:ExtA"])
        self.assertTrue(result["package_dir"].endswith("work\\1c-configuration-indexer\\out\\idx_relative_path"))


if __name__ == "__main__":
    unittest.main()
