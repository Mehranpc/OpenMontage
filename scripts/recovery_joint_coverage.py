#!/usr/bin/env python3
"""Read-only #382 increment B harness: frozen recovery frontier -> joint coverage.

Input is a JSON file holding one of: ``workflow status --json`` output, its
``acquisition.preparation`` object, a ``recoveryEvidence`` report, or an already
sanitized corpus. Output is the sanitized corpus plus its diagnostic certificate.
Nothing is selected, written to a project, searched, downloaded or rendered.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.persian_recovery_experiment import (  # noqa: E402
    CORPUS_VERSION,
    RecoveryExperimentError,
    joint_coverage_certificate,
    sanitize_recovery_corpus,
)


def _corpus(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("version") == CORPUS_VERSION:
        return dict(document)
    report: Any = document
    for key in ("acquisition", "preparation", "recoveryEvidence"):
        if isinstance(report, Mapping) and isinstance(report.get(key), Mapping):
            report = report[key]
    if not isinstance(report, Mapping) or "events" not in report:
        raise RecoveryExperimentError(
            "no recoveryEvidence found; it exists only when retry passes and send-backs are spent"
        )
    return sanitize_recovery_corpus(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--max-branches", type=int, default=20000)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise RecoveryExperimentError("input must be a JSON object")
        corpus = _corpus(document)
        certificate = joint_coverage_certificate(corpus, max_branches=args.max_branches)
    except (OSError, json.JSONDecodeError, RecoveryExperimentError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"corpus": corpus, "certificate": certificate},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
