"""Update critical OpenAPI contract snapshot used by tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app
from app.openapi_contract import extract_critical_openapi_contract

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "tests" / "contracts" / "openapi_critical_snapshot.json"


def main() -> int:
    contract = extract_critical_openapi_contract(app.openapi())
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated OpenAPI contract snapshot: {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
