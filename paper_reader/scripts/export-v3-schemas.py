#!/usr/bin/env python3
"""Export development v3 schemas without changing the released v2 namespace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from paper_reader.operations.contracts import V3_SCHEMA_MODELS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "references" / "official-schemas")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for version, model in V3_SCHEMA_MODELS.items():
        payload = json.dumps(model.model_json_schema(mode="validation"), ensure_ascii=False, indent=2, sort_keys=True)
        (args.output_dir / f"{version}.schema.json").write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
