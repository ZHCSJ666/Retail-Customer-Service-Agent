#!/usr/bin/env python3
"""Validate merchant fixtures and initialize the local SQLite session database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import MerchantCatalog  # noqa: E402
from app.core.database import SessionStore  # noqa: E402
from app.demo_data.repository import DemoDataRepository  # noqa: E402
from rag.ingest import ingest_merchant_knowledge  # noqa: E402
from rag.store import SQLiteRagStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merchant", default="star_select", help="Merchant ID to validate")
    parser.add_argument("--all-merchants", action="store_true", help="Validate and ingest every configured merchant")
    parser.add_argument(
        "--database",
        default="data/retail_customer_agent.db",
        help="SQLite path, relative to the project root unless absolute",
    )
    args = parser.parse_args()

    database_path = Path(args.database)
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    catalog = MerchantCatalog()
    repository = DemoDataRepository(catalog)
    try:
        store = SessionStore(database_path)
        merchant_ids = [merchant.config.merchant_id for merchant in catalog.all()] if args.all_merchants else [args.merchant]
        results = []
        rag_store = SQLiteRagStore(database_path)
        for merchant_id in merchant_ids:
            counts = repository.validate_merchant_fixtures(merchant_id)
            knowledge_index = ingest_merchant_knowledge(catalog.get(merchant_id), rag_store)
            results.append(
                {"merchant_id": merchant_id, "fixtures": counts, "knowledge_index": knowledge_index}
            )
        database_ready = store.ping()
    except (KeyError, RuntimeError) as exc:
        print(f"Initialization failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "merchants": results,
                "database": str(database_path),
                "database_ready": database_ready,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
