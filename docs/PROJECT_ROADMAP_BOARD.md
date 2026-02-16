# StaySense Project Board Seed

Quelle: `docs/ROADMAP_30_60_90.md` (Stand 2026-02-16)

## Spaltenvorschlag

- Backlog
- This Sprint
- In Progress
- Review
- Done

## Feldervorschlag

- `Status`: Todo, In Progress, Done
- `Iteration`: Bereits umgesetzt, 0-30 Tage, 31-60 Tage, 61-90 Tage
- `Priority`: P0..P3
- `Area`: frontend, backend, data, ops, docs

## Initiale Items

Siehe CSV-Import: `docs/PROJECT_ROADMAP_IMPORT.csv`

## Sync-Workflow (automatisch)

Tool:
- `scripts/sync_project_roadmap.py`

Dry-Run:

```bash
python3 scripts/sync_project_roadmap.py --project 4 --owner @me --dry-run
```

Ausfuehren:

```bash
python3 scripts/sync_project_roadmap.py --project 4 --owner @me --apply --create-fields
```

Was der Sync macht:

- Upsert per Titel (Draft-Items)
- Body aus CSV aktualisieren
- `Status` setzen
- `Roadmap Window` setzen (falls vorhanden/erzeugbar)
- `Priority` setzen (falls vorhanden/erzeugbar)

## Weekly Reminder (automatisch)

Workflow:
- `.github/workflows/roadmap-reminder.yml`

Script:
- `scripts/roadmap_reminder_report.py`

Manuell testen:

```bash
python3 scripts/roadmap_reminder_report.py \
  --repo OliverGiertz/StaySense \
  --project-owner OliverGiertz \
  --project-number 4 \
  --days-upcoming 14 \
  --dry-run
```

Produktiv (lokal):

```bash
python3 scripts/roadmap_reminder_report.py \
  --repo OliverGiertz/StaySense \
  --project-owner OliverGiertz \
  --project-number 4 \
  --days-upcoming 14
```

GitHub Actions Secret:
- `GH_PROJECT_TOKEN` (empfohlen, Scope: `repo`, `project`, `read:project`)
- Ohne dieses Secret laeuft der Report ggf. nur teilweise (Project-Felder evtl. nicht lesbar).

## Pflege-Regeln

1. Jede Roadmap-Task hat klare Akzeptanzkriterien.
2. Blocker sofort als Kommentar + Label `blocked`.
3. Bei Abschluss: Link zum Commit/PR hinterlegen.
4. Monatlich Iteration rollieren (30/60/90 neu zuschneiden).
