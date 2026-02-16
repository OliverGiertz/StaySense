#!/usr/bin/env python3
"""Sync roadmap CSV entries into a GitHub Project (v2) via gh CLI.

Usage examples:
  python3 scripts/sync_project_roadmap.py --project 4 --owner @me --dry-run
  python3 scripts/sync_project_roadmap.py --project 4 --owner @me --apply --create-fields
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_CSV = Path("docs/PROJECT_ROADMAP_IMPORT.csv")
DEFAULT_WINDOW_OPTIONS = ["Bereits umgesetzt", "0-30 Tage", "31-60 Tage", "61-90 Tage"]
DEFAULT_PRIORITY_OPTIONS = ["P0", "P1", "P2", "P3"]


def normalize(value: str) -> str:
    return "".join(ch for ch in value.lower().strip() if ch.isalnum())


def run_gh(args: list[str], expect_json: bool = False) -> dict | list | str:
    cmd = ["gh", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    output = proc.stdout.strip()
    if expect_json:
        return json.loads(output or "{}")
    return output


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_body(row: dict) -> str:
    body = (row.get("Body") or "").strip()
    iteration = (row.get("Iteration") or "").strip()
    priority = (row.get("Priority") or "").strip()
    labels = (row.get("Labels") or "").strip()
    meta = []
    if iteration:
        meta.append(f"- Iteration: {iteration}")
    if priority:
        meta.append(f"- Priority: {priority}")
    if labels:
        meta.append(f"- Labels: {labels}")
    if meta:
        return f"{body}\n\n---\nRoadmap-Metadaten:\n" + "\n".join(meta)
    return body


def find_field(fields: list[dict], name: str) -> dict | None:
    for field in fields:
        if field.get("name") == name:
            return field
    return None


def option_id_for(field: dict, wanted: str) -> str | None:
    options = field.get("options") or []
    if not options:
        return None
    wanted_norm = normalize(wanted)
    for option in options:
        name = option.get("name", "")
        if name == wanted or normalize(name) == wanted_norm:
            return option.get("id")
    return None


def ensure_single_select_field(
    project: int,
    owner: str,
    fields: list[dict],
    field_name: str,
    options: list[str],
    create_if_missing: bool,
    dry_run: bool,
) -> dict | None:
    existing = find_field(fields, field_name)
    if existing:
        return existing
    if not create_if_missing:
        return None
    if dry_run:
        print(f"[dry-run] would create field '{field_name}' with options {options}")
        return {"id": f"DRYRUN_{field_name}", "name": field_name, "options": [{"id": opt, "name": opt} for opt in options]}
    run_gh(
        [
            "project",
            "field-create",
            str(project),
            "--owner",
            owner,
            "--name",
            field_name,
            "--data-type",
            "SINGLE_SELECT",
            "--single-select-options",
            ",".join(options),
        ]
    )
    refreshed = run_gh(["project", "field-list", str(project), "--owner", owner, "--format", "json"], expect_json=True)
    return find_field(refreshed.get("fields", []), field_name)


def set_single_select(
    item_id: str,
    project_id: str,
    field: dict,
    value: str,
    dry_run: bool,
) -> None:
    option_id = option_id_for(field, value)
    if not option_id:
        print(f"[warn] option '{value}' not found in field '{field.get('name')}'")
        return
    if dry_run:
        print(f"[dry-run] set {field.get('name')}={value} for item {item_id}")
        return
    run_gh(
        [
            "project",
            "item-edit",
            "--id",
            item_id,
            "--project-id",
            project_id,
            "--field-id",
            field["id"],
            "--single-select-option-id",
            option_id,
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync roadmap CSV into GitHub Project")
    parser.add_argument("--project", type=int, required=True, help="Project number")
    parser.add_argument("--owner", required=True, help="Project owner login, e.g. @me or OliverGiertz")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Path to roadmap CSV")
    parser.add_argument("--apply", action="store_true", help="Apply changes (without this flag, dry-run is active)")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode")
    parser.add_argument("--create-fields", action="store_true", help="Create missing single-select fields")
    parser.add_argument("--status-field", default="Status")
    parser.add_argument("--window-field", default="Roadmap Window")
    parser.add_argument("--priority-field", default="Priority")
    args = parser.parse_args()

    dry_run = args.dry_run or not args.apply
    rows = read_csv_rows(args.csv)
    if not rows:
        print("No rows found in CSV.")
        return 0

    project_view = run_gh(
        ["project", "view", str(args.project), "--owner", args.owner, "--format", "json"],
        expect_json=True,
    )
    project_id = project_view["id"]

    fields_raw = run_gh(
        ["project", "field-list", str(args.project), "--owner", args.owner, "--format", "json"],
        expect_json=True,
    )
    fields = fields_raw.get("fields", [])

    status_field = find_field(fields, args.status_field)
    if not status_field:
        raise RuntimeError(f"Required field '{args.status_field}' not found in project.")

    window_field = ensure_single_select_field(
        project=args.project,
        owner=args.owner,
        fields=fields,
        field_name=args.window_field,
        options=DEFAULT_WINDOW_OPTIONS,
        create_if_missing=args.create_fields,
        dry_run=dry_run,
    )
    priority_field = ensure_single_select_field(
        project=args.project,
        owner=args.owner,
        fields=fields,
        field_name=args.priority_field,
        options=DEFAULT_PRIORITY_OPTIONS,
        create_if_missing=args.create_fields,
        dry_run=dry_run,
    )

    items_raw = run_gh(
        ["project", "item-list", str(args.project), "--owner", args.owner, "--format", "json"],
        expect_json=True,
    )
    items = items_raw.get("items", [])
    by_title = {item.get("title"): item for item in items if item.get("title")}

    created = 0
    updated = 0

    for row in rows:
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        body = build_body(row)
        status_value = (row.get("Status") or "Todo").strip() or "Todo"
        window_value = (row.get("Iteration") or "").strip()
        priority_value = (row.get("Priority") or "").strip()

        existing = by_title.get(title)
        if not existing:
            if dry_run:
                print(f"[dry-run] create item: {title}")
                item_id = f"DRYRUN_{normalize(title)[:16]}"
            else:
                created_item = run_gh(
                    [
                        "project",
                        "item-create",
                        str(args.project),
                        "--owner",
                        args.owner,
                        "--title",
                        title,
                        "--body",
                        body,
                        "--format",
                        "json",
                    ],
                    expect_json=True,
                )
                item_id = created_item["id"]
                by_title[title] = {"id": item_id, "title": title}
            created += 1
        else:
            item_id = existing["id"]
            if dry_run:
                print(f"[dry-run] update draft item: {title}")
            else:
                # Draft text updates require the DI_* content id (not PVTI_* item id).
                content = existing.get("content") or {}
                content_id = content.get("id", "")
                if content_id.startswith("DI_"):
                    run_gh(
                        [
                            "project",
                            "item-edit",
                            "--id",
                            content_id,
                            "--title",
                            title,
                            "--body",
                            body,
                        ]
                    )
                else:
                    print(f"[warn] skip body update for non-draft item '{title}'")
            updated += 1

        set_single_select(item_id, project_id, status_field, status_value, dry_run=dry_run)
        if window_field and window_value:
            set_single_select(item_id, project_id, window_field, window_value, dry_run=dry_run)
        if priority_field and priority_value:
            set_single_select(item_id, project_id, priority_field, priority_value, dry_run=dry_run)

    summary = {
        "project": args.project,
        "owner": args.owner,
        "csv_rows": len(rows),
        "created": created,
        "updated": updated,
        "dry_run": dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
