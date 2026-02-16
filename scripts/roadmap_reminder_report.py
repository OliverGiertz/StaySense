#!/usr/bin/env python3
"""Create or update a weekly roadmap health report issue."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], expect_json: bool = False) -> dict | list | str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    data = proc.stdout.strip()
    if expect_json:
        return json.loads(data or "{}")
    return data


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if "T" in text:
            return dt.date.fromisoformat(text.split("T", 1)[0])
        return dt.date.fromisoformat(text)
    except Exception:
        return None


def fetch_open_roadmap_issues(repo: str) -> list[dict]:
    payload = run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,title,milestone,labels,url",
        ],
        expect_json=True,
    )
    out = []
    for item in payload:
        labels = [it.get("name", "") for it in item.get("labels", [])]
        if "roadmap" not in labels:
            continue
        if "roadmap-report" in labels:
            continue
        out.append(item)
    return out


def fetch_project_metadata(project_number: int | None, project_owner: str | None) -> tuple[dict[int, dict], str | None]:
    if not project_number or not project_owner:
        return {}, "Project-Metadaten nicht konfiguriert (owner/number fehlen)."
    try:
        payload = run(
            [
                "gh",
                "project",
                "item-list",
                str(project_number),
                "--owner",
                project_owner,
                "--format",
                "json",
            ],
            expect_json=True,
        )
    except Exception as exc:
        return {}, f"Project-Metadaten nicht abrufbar: {exc}"

    out: dict[int, dict] = {}
    for item in payload.get("items", []):
        content = item.get("content") or {}
        if content.get("type") != "Issue":
            continue
        number = content.get("number")
        if not isinstance(number, int):
            continue
        out[number] = {
            "target_date": item.get("target date"),
            "start_date": item.get("start date"),
            "priority": item.get("priority"),
            "status": item.get("status"),
            "window": item.get("roadmap Window"),
        }
    return out, None


def build_report(issues: list[dict], project_meta: dict[int, dict], warning: str | None, upcoming_days: int) -> str:
    today = dt.date.today()
    threshold = today + dt.timedelta(days=upcoming_days)

    overdue = []
    upcoming = []
    no_deadline = []
    all_rows = []

    for issue in issues:
        number = issue["number"]
        meta = project_meta.get(number, {})
        milestone = issue.get("milestone") or {}
        milestone_due = parse_date(milestone.get("dueOn"))
        target_date = parse_date(meta.get("target_date"))
        deadline = target_date or milestone_due
        source = "target date" if target_date else ("milestone" if milestone_due else "-")
        days_left = (deadline - today).days if deadline else None

        row = {
            "number": number,
            "title": issue["title"],
            "url": issue["url"],
            "status": meta.get("status", "Todo"),
            "priority": meta.get("priority", "-"),
            "window": meta.get("window", "-"),
            "milestone": milestone.get("title", "-"),
            "deadline": deadline.isoformat() if deadline else "-",
            "source": source,
            "days_left": days_left,
        }
        all_rows.append(row)

        if not deadline:
            no_deadline.append(row)
        elif deadline < today:
            overdue.append(row)
        elif deadline <= threshold:
            upcoming.append(row)

    all_rows.sort(key=lambda r: (r["deadline"] == "-", r["deadline"], r["priority"], r["number"]))
    overdue.sort(key=lambda r: (r["deadline"], r["number"]))
    upcoming.sort(key=lambda r: (r["deadline"], r["number"]))
    no_deadline.sort(key=lambda r: r["number"])

    lines = []
    lines.append(f"# Roadmap Health Report ({today.isoformat()})")
    lines.append("")
    lines.append("Automatisch generierter Reminder fuer Roadmap-Issues.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Open roadmap issues: **{len(issues)}**")
    lines.append(f"- Overdue: **{len(overdue)}**")
    lines.append(f"- Upcoming (naechste {upcoming_days} Tage): **{len(upcoming)}**")
    lines.append(f"- Ohne Deadline: **{len(no_deadline)}**")
    lines.append("")
    if warning:
        lines.append(f"> Hinweis: {warning}")
        lines.append("")

    def section(name: str, rows: list[dict]) -> None:
        lines.append(f"## {name}")
        lines.append("")
        if not rows:
            lines.append("_Keine Eintraege._")
            lines.append("")
            return
        lines.append("| Issue | Titel | Status | Prio | Window | Deadline | Quelle | Tage |")
        lines.append("|---|---|---|---|---|---|---|---:|")
        for row in rows:
            days = "-" if row["days_left"] is None else str(row["days_left"])
            title = row["title"].replace("|", "/")
            lines.append(
                f"| [#{row['number']}]({row['url']}) | {title} | {row['status']} | {row['priority']} | "
                f"{row['window']} | {row['deadline']} | {row['source']} | {days} |"
            )
        lines.append("")

    section("Overdue", overdue)
    section(f"Upcoming (<= {upcoming_days} Tage)", upcoming)
    section("Ohne Deadline", no_deadline)
    section("Alle Open Roadmap Issues", all_rows)
    return "\n".join(lines).strip() + "\n"


def ensure_label(repo: str, label: str) -> None:
    run(
        [
            "gh",
            "label",
            "create",
            label,
            "--repo",
            repo,
            "--color",
            "8a2be2",
            "--description",
            "Automatischer Roadmap Report",
            "--force",
        ]
    )


def upsert_issue(repo: str, title: str, body_file: Path, labels: list[str]) -> str:
    payload = run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--search",
            f'in:title "{title}"',
            "--json",
            "number,title,url",
            "--limit",
            "20",
        ],
        expect_json=True,
    )
    existing = next((item for item in payload if item.get("title") == title), None)
    if not existing and labels:
        fallback = run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--label",
                labels[0],
                "--json",
                "number,title,url",
                "--limit",
                "20",
            ],
            expect_json=True,
        )
        existing = next((item for item in fallback if str(item.get("title", "")).startswith("[Roadmap] Weekly")), None)
    if existing:
        run(
            [
                "gh",
                "issue",
                "edit",
                str(existing["number"]),
                "--repo",
                repo,
                "--title",
                title,
                "--body-file",
                str(body_file),
            ]
        )
        for label in labels:
            run(["gh", "issue", "edit", str(existing["number"]), "--repo", repo, "--add-label", label])
        return existing["url"]

    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body-file",
        str(body_file),
    ]
    for label in labels:
        cmd.extend(["--label", label])
    url = run(cmd)
    return str(url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate roadmap reminder report and upsert issue")
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--project-owner", default="", help="Project owner login, e.g. @me or OliverGiertz")
    parser.add_argument("--project-number", type=int, default=0, help="Project number")
    parser.add_argument("--days-upcoming", type=int, default=7)
    parser.add_argument("--upsert-issue-title", default="[Roadmap] Weekly Deadlines (7 Tage)")
    parser.add_argument("--labels", default="roadmap-report,roadmap,ops", help="Comma-separated labels for report issue")
    parser.add_argument("--output-file", type=Path, default=Path("roadmap-health-report.md"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    issues = fetch_open_roadmap_issues(args.repo)
    project_meta, warning = fetch_project_metadata(
        project_number=args.project_number if args.project_number > 0 else None,
        project_owner=args.project_owner or None,
    )
    report = build_report(issues, project_meta, warning, args.days_upcoming)
    args.output_file.write_text(report, encoding="utf-8")
    print(f"Report written to {args.output_file}")

    if args.dry_run:
        print("[dry-run] skip issue upsert")
        print(report)
        return 0

    labels = [it.strip() for it in args.labels.split(",") if it.strip()]
    for label in labels:
        ensure_label(args.repo, label)
    issue_url = upsert_issue(args.repo, args.upsert_issue_title, args.output_file, labels)
    print(f"Report issue upserted: {issue_url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
