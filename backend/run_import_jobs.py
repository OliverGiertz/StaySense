import argparse
import json
import time
from pathlib import Path

from import_osm_overpass import DEFAULT_BBOX, import_osm
from open_data_connector import import_from_config


def run_once(config_path: Path, with_osm: bool, prune_legacy: bool, south: float, west: float, north: float, east: float) -> dict:
    result = {"open_data": import_from_config(config_path, prune_legacy=prune_legacy)}
    if with_osm:
        result["osm"] = import_osm(south, west, north, east)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StaySense data import jobs")
    parser.add_argument("--config", default="../docs/open_data_sources.json", help="Path to open data source config JSON")
    parser.add_argument("--with-osm", action="store_true", help="Also run OSM overpass import")
    parser.add_argument("--prune-legacy", action="store_true", help="Delete open_data_event sources not present in config")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval-seconds", type=int, default=21600, help="Loop interval for daemon mode")
    parser.add_argument("--south", type=float, default=DEFAULT_BBOX[0])
    parser.add_argument("--west", type=float, default=DEFAULT_BBOX[1])
    parser.add_argument("--north", type=float, default=DEFAULT_BBOX[2])
    parser.add_argument("--east", type=float, default=DEFAULT_BBOX[3])
    args = parser.parse_args()

    config_path = Path(args.config).resolve()

    if not args.daemon:
        print(json.dumps(run_once(config_path, args.with_osm, args.prune_legacy, args.south, args.west, args.north, args.east), ensure_ascii=True))
        return

    while True:
        result = run_once(config_path, args.with_osm, args.prune_legacy, args.south, args.west, args.north, args.east)
        print(json.dumps(result, ensure_ascii=True))
        time.sleep(max(60, args.interval_seconds))


if __name__ == "__main__":
    main()
