#!/usr/bin/env python3
"""Export the five active 3.0 batch contracts; core schemas remain core-owned."""
import argparse
import json
from pathlib import Path

from paper_reader_batch.official_workflow.contracts import BatchManifest, BatchState, BatchEvent, BatchReport, CommandResult


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
        default=Path(__file__).resolve().parents[1] / 'references' / 'official-schemas')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, model in (('manifest', BatchManifest), ('state', BatchState), ('event', BatchEvent),
                        ('report', BatchReport), ('command-result', CommandResult)):
        schema = json.dumps(model.model_json_schema(mode='validation'), ensure_ascii=False, indent=2, sort_keys=True)
        (args.output_dir / f'paper_reader_batch.{name}.v3.schema.json').write_text(schema + '\n')


if __name__ == '__main__':
    main()
