from __future__ import annotations

from collections import defaultdict

from .models import Flower, Seller, Supplier
from .repository import InMemoryRepository

ROUTE_STATUSES = ("created", "in_transit", "delivered")
TASK_STATUSES = ("open", "in_progress", "done")
TASK_PRIORITIES = ("normal", "high", "critical")

ROUTE_STATUS_LABELS = {
    "created": "Создан",
    "in_transit": "В пути",
    "delivered": "Доставлен",
}

TASK_STATUS_LABELS = {
    "open": "Открыта",
    "in_progress": "В работе",
    "done": "Выполнена",
}

TASK_PRIORITY_LABELS = {
    "normal": "Обычный",
    "high": "Высокий",
    "critical": "Критический",
}


class LogisticsService:
    def __init__(self, repo: InMemoryRepository) -> None:
        self.repo = repo

    def flower_filters(self) -> dict[str, list[str]]:
        flowers = self.repo.list_flowers()
        return {
            "seasons": sorted({flower.bloom_season for flower in flowers}),
            "countries": sorted({flower.country for flower in flowers}),
            "varieties": sorted({flower.variety for flower in flowers}),
        }

    def find_flowers(
        self,
        season: str | None = None,
        country: str | None = None,
        variety: str | None = None,
        supplier_id: int | None = None,
    ) -> list[Flower]:
        flowers = self.repo.list_flowers()

        def match(value: str | None, field: str) -> bool:
            return not value or field.lower() == value.lower()

        result = [
            flower
            for flower in flowers
            if match(season, flower.bloom_season)
            and match(country, flower.country)
            and match(variety, flower.variety)
            and (supplier_id is None or flower.supplier_id == supplier_id)
        ]
        return sorted(result, key=lambda item: (item.name, item.price))

    def supplier_overview(self) -> list[dict[str, object]]:
        suppliers = self.repo.list_suppliers()
        flowers = self.repo.list_flowers()

        supplier_flowers: dict[int, list[Flower]] = defaultdict(list)
        for flower in flowers:
            supplier_flowers[flower.supplier_id].append(flower)

        rows: list[dict[str, object]] = []
        for supplier in suppliers:
            items = sorted(supplier_flowers[supplier.id], key=lambda flower: flower.name)
            rows.append(
                {
                    "supplier": supplier,
                    "flowers": items,
                    "total_value": round(sum(flower.price for flower in items), 2),
                }
            )
        return rows

    def seller_overview(self) -> list[dict[str, object]]:
        sellers = self.repo.list_sellers()
        links = self.repo.seller_flowers

        seller_to_flower_ids: dict[int, set[int]] = defaultdict(set)
        for link in links:
            seller_to_flower_ids[link.seller_id].add(link.flower_id)

        rows: list[dict[str, object]] = []
        for seller in sellers:
            flowers = self.repo.get_flowers_by_ids(seller_to_flower_ids[seller.id])
            rows.append(
                {
                    "seller": seller,
                    "flowers": sorted(flowers, key=lambda flower: flower.name),
                }
            )
        return rows

    def route_overview(
        self,
        status: str | None = None,
        supplier_id: int | None = None,
        seller_id: int | None = None,
    ) -> list[dict[str, object]]:
        routes = self.repo.list_routes()

        rows: list[dict[str, object]] = []
        for route in routes:
            if status and route.status != status:
                continue
            if supplier_id and route.supplier_id != supplier_id:
                continue
            if seller_id and route.seller_id != seller_id:
                continue

            supplier = self.repo.get_supplier(route.supplier_id)
            seller = self.repo.get_seller(route.seller_id)
            flower = self.repo.get_flower(route.flower_id)
            if not supplier or not seller or not flower:
                continue

            rows.append(
                {
                    "route": route,
                    "supplier": supplier,
                    "seller": seller,
                    "flower": flower,
                    "cargo_value": round(route.quantity * flower.price, 2),
                }
            )

        return sorted(rows, key=lambda row: str(row["route"].planned_date), reverse=True)

    def task_board(
        self,
        status: str | None = None,
        priority: str | None = None,
    ) -> list[dict[str, object]]:
        tasks = self.repo.list_tasks()
        rows: list[dict[str, object]] = []

        for task in tasks:
            if status and task.status != status:
                continue
            if priority and task.priority != priority:
                continue

            route = self.repo.get_route(task.route_id)
            if not route:
                continue

            supplier = self.repo.get_supplier(route.supplier_id)
            seller = self.repo.get_seller(route.seller_id)
            if not supplier or not seller:
                continue

            rows.append(
                {
                    "task": task,
                    "route": route,
                    "supplier": supplier,
                    "seller": seller,
                }
            )

        return sorted(rows, key=lambda row: str(row["task"].due_date))

    def logistics_kpis(self) -> dict[str, int]:
        routes = self.repo.list_routes()
        tasks = self.repo.list_tasks()
        return {
            "flowers": len(self.repo.flowers),
            "suppliers": len(self.repo.suppliers),
            "sellers": len(self.repo.sellers),
            "routes": len(routes),
            "tasks": len(tasks),
            "created": sum(1 for route in routes if route.status == "created"),
            "in_transit": sum(1 for route in routes if route.status == "in_transit"),
            "delivered": sum(1 for route in routes if route.status == "delivered"),
            "tasks_done": sum(1 for task in tasks if task.status == "done"),
        }

    def completed_deliveries_report(self) -> list[dict[str, object]]:
        delivered_routes = [route for route in self.repo.list_routes() if route.status == "delivered"]
        task_by_route: dict[int, list[object]] = defaultdict(list)
        for task in self.repo.list_tasks():
            task_by_route[task.route_id].append(task)

        rows: list[dict[str, object]] = []
        for route in delivered_routes:
            supplier = self.repo.get_supplier(route.supplier_id)
            seller = self.repo.get_seller(route.seller_id)
            flower = self.repo.get_flower(route.flower_id)
            if not supplier or not seller or not flower:
                continue

            tasks = task_by_route[route.id]
            done_tasks = sum(1 for task in tasks if task.status == "done")
            rows.append(
                {
                    "route": route,
                    "supplier": supplier,
                    "seller": seller,
                    "flower": flower,
                    "task_total": len(tasks),
                    "task_done": done_tasks,
                    "task_completion": 100 if not tasks else round(done_tasks / len(tasks) * 100),
                }
            )
        return sorted(rows, key=lambda row: row["route"].id)

    def shared_suppliers(self, seller_a_id: int, seller_b_id: int) -> list[Supplier]:
        seller_to_suppliers: dict[int, set[int]] = defaultdict(set)
        for route in self.repo.list_routes():
            seller_to_suppliers[route.seller_id].add(route.supplier_id)

        common_ids = seller_to_suppliers[seller_a_id] & seller_to_suppliers[seller_b_id]
        suppliers = [supplier for supplier in self.repo.list_suppliers() if supplier.id in common_ids]
        return sorted(suppliers, key=lambda supplier: supplier.full_name)

    def sellers_with_most_routes(self) -> list[dict[str, object]]:
        count_by_seller: dict[int, int] = defaultdict(int)
        for route in self.repo.list_routes():
            count_by_seller[route.seller_id] += 1

        rows: list[dict[str, object]] = []
        for seller in self.repo.list_sellers():
            rows.append({"seller": seller, "route_count": count_by_seller[seller.id]})

        return sorted(rows, key=lambda row: row["route_count"], reverse=True)
