from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import configuration_indexer.package_uploader as uploader
from configuration_indexer.package_uploader import PackageUploadOptions, retry_failed_chunks, upload_package


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

    def test_stops_upload_after_unrecoverable_chunk_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "job_id": "idx_test_failed_chunk",
                        "schema_version": "configuration-mcp/index-package/1",
                        "chunks": [
                            {
                                "file": "chunks/configuration_entities.000001.jsonl.gz",
                                "table": "configuration_entities",
                                "sha256": "abc",
                                "rows": 1,
                            },
                            {
                                "file": "chunks/configuration_search_chunks.000001.jsonl.gz",
                                "table": "configuration_search_chunks",
                                "sha256": "def",
                                "rows": 1,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            chunk_calls: list[str] = []

            def fake_post_bytes(options, data, headers):  # type: ignore[no-untyped-def]
                return {
                    "ok": True,
                    "status_code": 200,
                    "response_text": "",
                    "response_json": {"ok": True},
                }

            def fake_post_chunk(options, manifest, chunk, chunk_path, position, chunk_count):  # type: ignore[no-untyped-def]
                chunk_calls.append(chunk["file"])
                return {
                    "ok": False,
                    "status_code": 500,
                    "response_text": "",
                    "response_json": {"ok": False},
                }

            with (
                patch.object(uploader, "post_bytes", side_effect=fake_post_bytes),
                patch.object(uploader, "post_chunk", side_effect=fake_post_chunk),
            ):
                result = upload_package(
                    PackageUploadOptions(
                        manifest_path=manifest_path,
                        upload_url="https://example.test/upload",
                        max_retries=2,
                        retry_delay_seconds=0,
                    )
                )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "chunk upload failed: chunks/configuration_entities.000001.jsonl.gz")
        self.assertEqual(chunk_calls, ["chunks/configuration_entities.000001.jsonl.gz"] * 2)
        self.assertEqual(len(result.failed_chunks), 1)
        self.assertIsNone(result.complete_status)

    def test_retries_failed_chunks_in_dependency_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            failed_log_path = Path(tmp) / "upload-result.json"
            manifest = {
                "job_id": "idx_retry",
                "schema_version": "configuration-mcp/index-package/1",
                "row_count": 3,
                "package_bytes": 100,
                "chunks": [
                    {
                        "file": "chunks/configuration_search_chunks.000001.jsonl.gz",
                        "table": "configuration_search_chunks",
                        "chunk_index": 1,
                        "sha256": "search",
                        "rows": 1,
                    },
                    {
                        "file": "chunks/configuration_relations.000001.jsonl.gz",
                        "table": "configuration_relations",
                        "chunk_index": 1,
                        "sha256": "rel",
                        "rows": 1,
                    },
                    {
                        "file": "chunks/configuration_entities.000001.jsonl.gz",
                        "table": "configuration_entities",
                        "chunk_index": 1,
                        "sha256": "entity",
                        "rows": 1,
                    },
                ],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            failed_log_path.write_text(
                json.dumps(
                    {
                        "failed_chunks": [
                            {"chunk": manifest["chunks"][0], "response": {"ok": False}},
                            {"chunk": manifest["chunks"][1], "response": {"ok": False}},
                            {"chunk": manifest["chunks"][2], "response": {"ok": False}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            upload_order: list[str] = []
            complete_parts: list[str] = []

            def fake_post_chunk(options, manifest, chunk, chunk_path, position, chunk_count):  # type: ignore[no-untyped-def]
                upload_order.append(chunk["table"])
                return {
                    "ok": True,
                    "status_code": 200,
                    "response_text": "",
                    "response_json": {"ok": True},
                }

            def fake_post_bytes(options, data, headers):  # type: ignore[no-untyped-def]
                complete_parts.append(headers["X-Configuration-Upload-Part"])
                return {
                    "ok": True,
                    "status_code": 200,
                    "response_text": "",
                    "response_json": {"ok": True},
                }

            with (
                patch.object(uploader, "post_chunk", side_effect=fake_post_chunk),
                patch.object(uploader, "post_bytes", side_effect=fake_post_bytes),
            ):
                result = retry_failed_chunks(
                    PackageUploadOptions(
                        manifest_path=manifest_path,
                        upload_url="https://example.test/upload",
                        retry_delay_seconds=0,
                    ),
                    failed_log_path,
                )

        self.assertTrue(result.ok)
        self.assertEqual(
            upload_order,
            ["configuration_entities", "configuration_relations", "configuration_search_chunks"],
        )
        self.assertEqual(complete_parts, ["complete"])


if __name__ == "__main__":
    unittest.main()
