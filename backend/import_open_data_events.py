import argparse
import csv
import json
from pathlib import Path

from open_data_connector import import_event_rows


def import_events(csv_path: Path) -> dict:
    rows = []
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"lat", "lon", "event_type", "start_datetime", "end_datetime", "risk_modifier"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"CSV missing required columns: {sorted(required)}")

        for line in reader:
            rows.append(
                {
                    "id": None,
                    "event_type": (line.get("event_type") or "").strip(),
                    "lat": (line.get("lat") or "").strip(),
                    "lon": (line.get("lon") or "").strip(),
                    "start_datetime": (line.get("start_datetime") or "").strip(),
                    "end_datetime": (line.get("end_datetime") or "").strip(),
                    "risk_modifier": (line.get("risk_modifier") or "0").strip(),
                }
            )

    # Legacy CSV import keeps source-name bound to filename.
    source_name = f"open_data_events:{csv_path.name}"
    normalized = []
    for idx, row in enumerate(rows):
        row["id"] = f"{source_name}:{idx}"
        normalized.append(row)

    result = import_event_rows(normalized, source_name=source_name, notes=str(csv_path))
    result["source"] = str(csv_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Open Data events CSV for StaySense")
    parser.add_argument("--file", required=True, help="CSV with lat,lon,event_type,start_datetime,end_datetime,risk_modifier,source")
    args = parser.parse_args()

    result = import_events(Path(args.file))
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
