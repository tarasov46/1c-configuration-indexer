from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import configuration_indexer.package_uploader as uploader
from configuration_indexer.package_uploader import PackageUploadOptions, upload_package


class PackageUploaderTests(unittest.TestCase):
    def test_skips_chunks_when_manifest_is_already_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "job_id": "idx_test_completed",
                        "schema_version": "configuration-mcp/index-package/1",
                        "chunks": [
                            {
                                "file": "chunks/configuration_entities.000001.jsonl.gz",
                                "table": "configuration_entities",
                                "sha256": "abc",
                                "rows": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            calls: list[str] = []

            def fake_post_bytes(options, data, headers):  # type: ignore[no-untyped-def]
                calls.append(headers["X-Configuration-Upload-Part"])
                return {
                    "ok": True,
                    "status_code": 200,
                    "response_text": "",
                    "response_json": {"ok": True, "data": {"already_completed": True}},
                }

            with patch.object(uploader, "post_bytes", side_effect=fake_post_bytes):
                result = upload_package(
                    PackageUploadOptions(
                        manifest_path=manifest_path,
                        upload_url="https://example.test/upload",
                    )
                )

        self.assertTrue(result.ok)
        self.assertEqual(calls, ["manifest"])
        self.assertEqual(result.uploaded_chunks, 0)
        self.assertIsNone(result.complete_status)


if __name__ == "__main__":
    unittest.main()
