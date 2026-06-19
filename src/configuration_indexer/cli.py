from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .detector import detect_source, source_info_to_dict
from .indexer import IndexOptions, parse_configuration, write_outputs
from .package import DEFAULT_MAX_CHUNK_BYTES, PackageOptions, write_index_package
from .package_uploader import PackageUploadOptions, upload_package
from .project import ProjectIndexOptions, detect_project, parse_project, project_info_to_dict, write_project_manifest


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="configuration-indexer")
    subparsers = parser.add_subparsers(dest="command")

    detect_parser = subparsers.add_parser("detect", help="Detect 1C export kind")
    detect_parser.add_argument("--src", required=True, help="Path to 1C XML/BSL export")

    detect_project_parser = subparsers.add_parser("detect-project", help="Detect 1C project folder")
    detect_project_parser.add_argument("--root", required=True, help="Path to project folder with src and extensions")

    index_parser = subparsers.add_parser("index", help="Index 1C XML/BSL export")
    index_parser.add_argument("--src", required=True, help="Path to 1C XML/BSL export")
    index_parser.add_argument("--mode", default="auto", choices=["auto", "standard", "client_base", "extension", "external"])
    index_parser.add_argument("--product-code", default="")
    index_parser.add_argument("--release-version", default="")
    index_parser.add_argument("--snapshot-id", default="")
    index_parser.add_argument("--out-json", required=True)
    index_parser.add_argument("--out-summary", default="")
    index_parser.add_argument("--no-code-text", action="store_true")

    project_parser = subparsers.add_parser("index-project", help="Index project folder with src and extensions")
    project_parser.add_argument("--root", required=True, help="Path to project folder with src and extensions")
    project_parser.add_argument("--client-id", default="")
    project_parser.add_argument("--base-id", default="")
    project_parser.add_argument("--base-profile-id", default="")
    project_parser.add_argument("--profile-name", default="")
    project_parser.add_argument("--base-mode", default="index", choices=["detect", "index"])
    project_parser.add_argument("--product-code", default="")
    project_parser.add_argument("--release-version", default="")
    project_parser.add_argument("--standard-snapshot-id", default="")
    project_parser.add_argument("--out-json", required=True)
    project_parser.add_argument("--out-summary", default="")
    project_parser.add_argument("--no-code-text", action="store_true")
    project_parser.add_argument("--write-manifest", action="store_true")

    run_project_parser = subparsers.add_parser("run-project", help="Index project into one debug JSON")
    run_project_parser.add_argument("--root", required=True, help="Path to project folder with src and extensions")
    run_project_parser.add_argument("--out-dir", default="out")
    run_project_parser.add_argument("--client-id", default="")
    run_project_parser.add_argument("--base-id", default="")
    run_project_parser.add_argument("--base-profile-id", default="")
    run_project_parser.add_argument("--profile-name", default="")
    run_project_parser.add_argument("--base-mode", default="detect", choices=["detect", "index"])
    run_project_parser.add_argument("--product-code", default="")
    run_project_parser.add_argument("--release-version", default="")
    run_project_parser.add_argument("--standard-snapshot-id", default="")
    run_project_parser.add_argument("--no-code-text", action="store_true")
    run_project_parser.add_argument("--write-manifest", action="store_true")

    run_job_parser = subparsers.add_parser("run-job", help="Run autonomous indexing job from JSON")
    run_job_parser.add_argument("--job", required=True, help="Indexing job JSON")
    run_job_parser.add_argument("--out-dir", default="", help="Override job output directory")
    run_job_parser.add_argument("--no-upload", action="store_true")

    upload_package_parser = subparsers.add_parser("upload-package", help="Upload package manifest and chunks")
    upload_package_parser.add_argument("--manifest", required=True)
    upload_package_parser.add_argument("--upload-url", required=True)
    upload_package_parser.add_argument("--token", default="")
    upload_package_parser.add_argument("--token-env", default="")
    upload_package_parser.add_argument("--auth-header", default="Authorization")
    upload_package_parser.add_argument("--auth-scheme", default="Bearer")
    upload_package_parser.add_argument("--timeout-seconds", type=float, default=300)
    upload_package_parser.add_argument("--no-complete", action="store_true")
    upload_package_parser.add_argument("--transport", default="binary", choices=["binary", "staged-json"])

    args = parser.parse_args(argv)
    if args.command == "detect":
        info = detect_source(Path(args.src))
        print(json.dumps(source_info_to_dict(info), ensure_ascii=False, indent=2))
        return 0 if info.is_valid else 2

    if args.command == "detect-project":
        layout = detect_project(Path(args.root))
        print(json.dumps(project_info_to_dict(layout), ensure_ascii=False, indent=2))
        return 0 if layout.is_valid else 2

    if args.command == "index":
        index = parse_configuration(
            IndexOptions(
                src_root=Path(args.src),
                mode=args.mode,
                product_code=args.product_code,
                release_version=args.release_version,
                snapshot_id=args.snapshot_id,
                include_code_text=not args.no_code_text,
            )
        )
        write_outputs(index, Path(args.out_json), Path(args.out_summary) if args.out_summary else None)
        print(json.dumps(index["summary"], ensure_ascii=False, indent=2))
        return 0

    if args.command == "index-project":
        index = parse_project(
            ProjectIndexOptions(
                project_root=Path(args.root),
                include_code_text=not args.no_code_text,
                base_mode=args.base_mode,
                product_code=args.product_code,
                release_version=args.release_version,
                client_id=args.client_id,
                base_id=args.base_id,
                base_profile_id=args.base_profile_id,
                profile_name=args.profile_name,
                standard_snapshot_id=args.standard_snapshot_id,
            )
        )
        write_outputs(index, Path(args.out_json), Path(args.out_summary) if args.out_summary else None)
        if args.write_manifest:
            write_project_manifest(index)
        print(json.dumps(index["summary"], ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-project":
        out_dir = Path(args.out_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        index = parse_project(
            ProjectIndexOptions(
                project_root=Path(args.root),
                include_code_text=not args.no_code_text,
                base_mode=args.base_mode,
                product_code=args.product_code,
                release_version=args.release_version,
                client_id=args.client_id,
                base_id=args.base_id,
                base_profile_id=args.base_profile_id,
                profile_name=args.profile_name,
                standard_snapshot_id=args.standard_snapshot_id,
            )
        )
        out_json = out_dir / f"configuration_project_index_{timestamp}.json"
        out_summary = out_dir / f"configuration_project_index_{timestamp}.md"
        write_outputs(index, out_json, out_summary)
        if args.write_manifest:
            write_project_manifest(index)

        result = {
            "summary": index["summary"],
            "payload": str(out_json),
            "summary_path": str(out_summary),
            "manifest_path": index.get("project_info", {}).get("manifest_path") if args.write_manifest else "",
        }

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-job":
        result = run_job(Path(args.job), Path(args.out_dir) if args.out_dir else None, no_upload=args.no_upload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else int(result.get("exit_code") or 1)

    if args.command == "upload-package":
        upload_result = upload_package(
            PackageUploadOptions(
                manifest_path=Path(args.manifest),
                upload_url=args.upload_url,
                token=args.token,
                token_env=args.token_env,
                auth_header=args.auth_header,
                auth_scheme=args.auth_scheme,
                timeout_seconds=args.timeout_seconds,
                send_complete=not args.no_complete,
                transport=args.transport,
            )
        )
        print(json.dumps(upload_result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if upload_result.ok else 3

    parser.print_help()
    return 1


def run_job(job_path: Path, out_dir_override: Path | None = None, no_upload: bool = False) -> dict:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    input_config = job.get("input") or {}
    profile = job.get("profile") or {}
    output = job.get("output") or {}
    upload = job.get("upload") or {}

    source_path = Path(
        input_config.get("source_path")
        or input_config.get("project_root")
        or input_config.get("path")
        or job.get("source_path")
        or ""
    )
    if not source_path:
        return {"ok": False, "exit_code": 2, "error": "input.source_path is required"}

    out_dir = out_dir_override or Path(output.get("out_dir") or "out")
    package_name = output.get("package_name") or f"index-package-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    package_dir = out_dir / package_name
    include_code_text = bool(input_config.get("include_code_text", False))
    max_chunk_bytes = int(input_config.get("max_chunk_bytes") or upload.get("max_chunk_bytes") or DEFAULT_MAX_CHUNK_BYTES)
    job_id = str(job.get("job_id") or job.get("id") or package_name)

    layout = detect_project(source_path)
    if layout.is_valid and not input_config.get("force_single_source"):
        index = parse_project(
            ProjectIndexOptions(
                project_root=source_path,
                include_code_text=include_code_text,
                base_mode=input_config.get("base_mode") or "detect",
                product_code=input_config.get("product_code") or "",
                release_version=input_config.get("release_version") or "",
                client_id=profile.get("client_id") or "",
                base_id=profile.get("base_id") or "",
                base_profile_id=profile.get("base_profile_id") or "",
                profile_name=profile.get("profile_name") or "",
                standard_snapshot_id=input_config.get("standard_snapshot_id") or "",
            )
        )
    else:
        source_info = detect_source(source_path)
        if not source_info.is_valid:
            return {"ok": False, "exit_code": 2, "error": source_info.error}
        index = parse_configuration(
            IndexOptions(
                src_root=source_path,
                mode=input_config.get("mode") or "auto",
                product_code=input_config.get("product_code") or "",
                release_version=input_config.get("release_version") or "",
                snapshot_id=input_config.get("snapshot_id") or "",
                include_code_text=include_code_text,
            )
        )

    manifest = write_index_package(
        index,
        PackageOptions(
            package_dir=package_dir,
            max_chunk_bytes=max_chunk_bytes,
            job_id=job_id,
        ),
    )

    result = {
        "ok": True,
        "job_id": job_id,
        "package_dir": str(package_dir),
        "manifest_path": manifest["manifest_path"],
        "chunk_count": manifest["chunk_count"],
        "row_count": manifest["row_count"],
        "package_bytes": manifest["package_bytes"],
        "summary": manifest.get("summary") or {},
        "upload": None,
    }

    upload_enabled = bool(upload.get("enabled")) and not no_upload
    if upload_enabled:
        upload_result = upload_package(
            PackageUploadOptions(
                manifest_path=Path(manifest["manifest_path"]),
                upload_url=upload.get("upload_url") or upload.get("url") or "",
                token=upload.get("token") or "",
                token_env=upload.get("token_env") or "",
                auth_header=upload.get("auth_header") or "Authorization",
                auth_scheme=upload.get("auth_scheme") or "Bearer",
                timeout_seconds=float(upload.get("timeout_seconds") or 300),
                send_complete=upload.get("send_complete", True) is not False,
                transport=upload.get("transport") or "binary",
            )
        )
        result["upload"] = upload_result.to_dict()
        if not upload_result.ok:
            result["ok"] = False
            result["exit_code"] = 3

    return result


if __name__ == "__main__":
    raise SystemExit(main())
