#!/usr/bin/env python3
"""Import a Claude JSON export locally, publishing only approved article records."""
import argparse
import json
from pathlib import Path
from collect import read_json, write_json, validate_articles


def unwrap(value, key):
    if isinstance(value, dict):
        value = value.get(key, value.get("documents"))
    if not isinstance(value, list):
        raise ValueError("Expected an array or an object containing " + key)
    result = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Each record must be an object")
        if isinstance(row.get("data"), dict):
            row = {**row["data"], **({"id": row["id"]} if row.get("id") else {})}
        result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", required=True, type=Path)
    parser.add_argument("--rates", type=Path)
    parser.add_argument("--output", default=Path("data"), type=Path)
    args = parser.parse_args()
    records = unwrap(read_json(args.articles), "articles")
    published = [a for a in records if a.get("status") == "published"]
    validate_articles(published)
    current = read_json(args.output / "articles.json", [])
    validate_articles(current)
    merged = {a["id"]: a for a in current}
    merged.update({a["id"]: a for a in published})
    write_json(args.output / "articles.json", list(merged.values()))
    if args.rates:
        write_json(args.output / "rates.json", unwrap(read_json(args.rates), "rates"))
    print("Imported %d published articles; excluded %d unpublished records." %
          (len(published), len(records) - len(published)))
    print("Review the output before uploading. Never upload messages or subscriber exports.")


if __name__ == "__main__":
    main()
