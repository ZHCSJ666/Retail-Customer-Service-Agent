"""Merchant-scoped, read-only access to JSON demo fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import LoadedMerchant, MerchantCatalog


class DemoDataRepository:
    """Loads fixture collections through merchant configuration, never user input paths."""

    def __init__(self, merchant_catalog: MerchantCatalog) -> None:
        self.merchant_catalog = merchant_catalog
        self._cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _collection(self, merchant: LoadedMerchant, dataset: str) -> list[dict[str, Any]]:
        cache_key = (merchant.config.merchant_id, dataset)
        if cache_key not in self._cache:
            path = merchant.mock_data_path(dataset)
            self._cache[cache_key] = self._read_list(path)
        return self._cache[cache_key]

    @staticmethod
    def _read_list(path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid demo fixture: {path}") from exc
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise RuntimeError(f"Demo fixture must be a JSON object list: {path}")
        return payload

    def customers(self, merchant_id: str) -> list[dict[str, Any]]:
        merchant = self.merchant_catalog.get(merchant_id)
        return self._collection(merchant, "customers")

    def customer_exists(self, merchant_id: str, customer_id: str) -> bool:
        return any(customer.get("customer_id") == customer_id for customer in self.customers(merchant_id))

    def orders_for_customer(self, merchant_id: str, customer_id: str) -> list[dict[str, Any]]:
        merchant = self.merchant_catalog.get(merchant_id)
        return [
            order for order in self._collection(merchant, "orders") if order.get("customer_id") == customer_id
        ]

    def order_by_id(self, merchant_id: str, order_id: str) -> dict[str, Any] | None:
        merchant = self.merchant_catalog.get(merchant_id)
        return next(
            (order for order in self._collection(merchant, "orders") if order.get("order_id") == order_id),
            None,
        )

    def product_by_id(self, merchant_id: str, product_id: str) -> dict[str, Any] | None:
        merchant = self.merchant_catalog.get(merchant_id)
        return next(
            (product for product in self._collection(merchant, "products") if product.get("product_id") == product_id),
            None,
        )

    def validate_merchant_fixtures(self, merchant_id: str) -> dict[str, int]:
        """Validate Phase 1 fixture completeness before an API process is started."""

        merchant = self.merchant_catalog.get(merchant_id)
        products = self._collection(merchant, "products")
        customers = self._collection(merchant, "customers")
        orders = self._collection(merchant, "orders")
        failures = self._collection(merchant, "failure_scenarios")
        documents = sorted(merchant.knowledge_dir.glob("*.md")) + sorted(merchant.knowledge_dir.glob("*.txt"))

        requirements = merchant.config.demo_requirements
        statuses = {str(order.get("status")) for order in orders}
        required_statuses = set(requirements.required_order_statuses)
        if len(products) < requirements.min_products:
            raise RuntimeError(f"Demo data needs at least {requirements.min_products} products")
        if len(customers) < requirements.min_customers:
            raise RuntimeError(f"Demo data needs at least {requirements.min_customers} customers")
        if len(orders) < requirements.min_orders:
            raise RuntimeError(f"Demo data needs at least {requirements.min_orders} orders")
        if not required_statuses.issubset(statuses):
            raise RuntimeError("Demo orders do not cover all merchant-required statuses")
        if len(documents) < requirements.min_knowledge_documents:
            raise RuntimeError(
                f"Demo data needs at least {requirements.min_knowledge_documents} Markdown/TXT knowledge documents"
            )
        if len(failures) < requirements.min_failure_scenarios:
            raise RuntimeError(
                f"Demo data needs at least {requirements.min_failure_scenarios} documented failure scenarios"
            )
        if not merchant.prompt_path.is_file():
            raise RuntimeError(f"Missing merchant prompt: {merchant.prompt_path}")
        return {
            "products": len(products),
            "customers": len(customers),
            "orders": len(orders),
            "knowledge_documents": len(documents),
            "failure_scenarios": len(failures),
        }
