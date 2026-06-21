from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from configuration_indexer.package import rechunk_package, write_table_chunks


class PackageTests(unittest.TestCase):
    def test_rechunks_existing_package_without_losing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            target_dir = root / "target"
            chunks_dir = source_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            rows_by_table = {
                "schema_version": "configuration-mcp/v2",
                "configuration_entities": [
                    {"id": f"entity-{i}", "name": "x" * 220, "search_text": "entity"}
                    for i in range(3000)
                ],
                "configuration_search_chunks": [
                    {"id": f"card-{i}", "entity_id": f"entity-{i}", "search_text": "card"}
                    for i in range(3000)
                ],
            }
            chunks = []
            chunks.extend(write_table_chunks("configuration_entities", rows_by_table["configuration_entities"], chunks_dir, 512 * 1024))
            chunks.extend(
                write_table_chunks(
                    "configuration_search_chunks",
                    rows_by_table["configuration_search_chunks"],
                    chunks_dir,
                    512 * 1024,
                )
            )
            source_manifest = {
                "schema_version": "configuration-mcp/index-package/1",
                "job_id": "idx_old",
                "chunks": chunks,
                "chunk_count": len(chunks),
                "row_count": sum(chunk["rows"] for chunk in chunks),
                "package_bytes": sum(chunk["bytes"] for chunk in chunks),
                "manifest_path": str(source_dir / "manifest.json"),
            }
            Path(source_manifest["manifest_path"]).write_text(json.dumps(source_manifest), encoding="utf-8")

            target_manifest = rechunk_package(
                Path(source_manifest["manifest_path"]),
                target_dir,
                max_chunk_bytes=128 * 1024,
                job_id="idx_new",
            )

            source_rows = read_package_rows(source_manifest)
            target_rows = read_package_rows(target_manifest)

        self.assertEqual(target_manifest["job_id"], "idx_new")
        self.assertEqual(target_manifest["rechunked_from_job_id"], "idx_old")
        self.assertGreater(target_manifest["chunk_count"], source_manifest["chunk_count"])
        self.assertEqual(source_rows, target_rows)
        self.assertEqual(
            [chunk["table"] for chunk in target_manifest["chunks"][:2]],
            ["configuration_entities", "configuration_entities"],
        )


def read_package_rows(manifest: dict) -> list[dict]:
    manifest_path = Path(manifest["manifest_path"])
    rows: list[dict] = []
    for chunk in manifest["chunks"]:
        with gzip.open(manifest_path.parent / chunk["file"], "rt", encoding="utf-8") as f:
            rows.extend(json.loads(line) for line in f if line.strip())
    return rows


if __name__ == "__main__":
    unittest.main()
