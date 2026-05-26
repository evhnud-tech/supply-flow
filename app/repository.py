from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional until Postgres is used
    psycopg = None
    dict_row = None

from .models import DeliveryRoute, Flower, LogisticsTask, Seller, SellerFlower, Supplier, User


class InMemoryRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.database_url = os.getenv("DATABASE_URL")
        self.backend = "postgres" if self.database_url else "sqlite"
        base_dir = Path(__file__).resolve().parent
        self.db_path = Path(db_path) if db_path else base_dir / "data" / "supplyflow.sqlite3"
        if self.backend == "sqlite":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()
        self._seed_if_needed()
        self._ensure_entity_users()

    @property
    def flowers(self) -> list[Flower]:
        return self.list_flowers()

    @property
    def suppliers(self) -> list[Supplier]:
        return self.list_suppliers()

    @property
    def sellers(self) -> list[Seller]:
        return self.list_sellers()

    @property
    def seller_flowers(self) -> list[SellerFlower]:
        with self._connect() as connection:
            rows = connection.execute(self._sql("SELECT seller_id, flower_id FROM seller_flowers ORDER BY seller_id, flower_id")).fetchall()
        return [SellerFlower(seller_id=row["seller_id"], flower_id=row["flower_id"]) for row in rows]

    @property
    def users(self) -> list[User]:
        return self.list_users()

    def _connect(self) -> sqlite3.Connection:
        if self.backend == "sqlite":
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        if psycopg is None or dict_row is None:
            raise RuntimeError("Install psycopg[binary] to use PostgreSQL via DATABASE_URL")

        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _initialize_database(self) -> None:
        if self.backend == "sqlite":
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS suppliers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT NOT NULL,
                        farm_type TEXT NOT NULL,
                        address TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS flowers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        species TEXT NOT NULL,
                        variety TEXT NOT NULL,
                        country TEXT NOT NULL,
                        bloom_season TEXT NOT NULL,
                        room_type TEXT NOT NULL,
                        price REAL NOT NULL,
                        supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS sellers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT NOT NULL,
                        address TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS seller_flowers (
                        seller_id INTEGER NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
                        flower_id INTEGER NOT NULL REFERENCES flowers(id) ON DELETE CASCADE,
                        PRIMARY KEY (seller_id, flower_id)
                    );

                    CREATE TABLE IF NOT EXISTS routes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                        seller_id INTEGER NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
                        flower_id INTEGER NOT NULL REFERENCES flowers(id) ON DELETE CASCADE,
                        quantity INTEGER NOT NULL,
                        transport_type TEXT NOT NULL,
                        planned_date TEXT NOT NULL,
                        distance_km REAL NOT NULL,
                        status TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        assignee TEXT NOT NULL,
                        due_date TEXT NOT NULL,
                        priority TEXT NOT NULL,
                        status TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        password TEXT NOT NULL,
                        role TEXT NOT NULL,
                        full_name TEXT NOT NULL,
                        entity_id INTEGER
                    );
                    """
                )
            return

        with self._connect() as connection:
            connection.execute("SET client_encoding TO 'UTF8'")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS suppliers (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    farm_type TEXT NOT NULL,
                    address TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS flowers (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    name TEXT NOT NULL,
                    species TEXT NOT NULL,
                    variety TEXT NOT NULL,
                    country TEXT NOT NULL,
                    bloom_season TEXT NOT NULL,
                    room_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS sellers (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    address TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS seller_flowers (
                    seller_id INTEGER NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
                    flower_id INTEGER NOT NULL REFERENCES flowers(id) ON DELETE CASCADE,
                    PRIMARY KEY (seller_id, flower_id)
                );

                CREATE TABLE IF NOT EXISTS routes (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                    seller_id INTEGER NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
                    flower_id INTEGER NOT NULL REFERENCES flowers(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL,
                    transport_type TEXT NOT NULL,
                    planned_date TEXT NOT NULL,
                    distance_km REAL NOT NULL,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    assignee TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    entity_id INTEGER
                );
                """
            )

    def _sql(self, query: str) -> str:
        return query.replace("?", "%s") if self.backend == "postgres" else query

    def _fetchall(self, query: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(connection.execute(self._sql(query), params).fetchall())

    def _fetchone(self, query: str, params: tuple[object, ...] = ()) -> object | None:
        with self._connect() as connection:
            return connection.execute(self._sql(query), params).fetchone()

    def _insert_row(self, table: str, columns: list[str], values: tuple[object, ...]) -> object:
        placeholders = ", ".join("?" for _ in columns)
        columns_sql = ", ".join(columns)
        query = f"INSERT INTO {table} ({columns_sql}) VALUES ({placeholders})"
        if self.backend == "postgres":
            query += " RETURNING *"

        with self._connect() as connection:
            cursor = connection.execute(self._sql(query), values)
            if self.backend == "postgres":
                row = cursor.fetchone()
            else:
                row = connection.execute(self._sql(f"SELECT * FROM {table} WHERE id = ?"), (cursor.lastrowid,)).fetchone()
        return row

    def _update_row(self, table: str, set_clause: str, params: tuple[object, ...], where_clause: str, where_params: tuple[object, ...]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(self._sql(f"UPDATE {table} SET {set_clause} WHERE {where_clause}"), params + where_params)
            return cursor.rowcount

    def _delete_row(self, table: str, where_clause: str, params: tuple[object, ...]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(self._sql(f"DELETE FROM {table} WHERE {where_clause}"), params)
            return cursor.rowcount

    def _seed_if_needed(self) -> None:
        with self._connect() as connection:
            supplier_count = connection.execute("SELECT COUNT(*) AS count FROM suppliers").fetchone()["count"]
            if supplier_count:
                return

            rose_house = self.create_supplier("Rose House", "Теплица", "Москва, Тверская, 10")
            eco_garden = self.create_supplier("Eco Garden", "Открытый грунт", "Краснодар, улица Мира, 8")
            urban_bloom = self.create_supplier("Urban Bloom", "Оранжерея", "Санкт-Петербург, Невский проспект, 25")

            flower_1 = self.create_flower(
                name="Пионовый румянец",
                species="Пион",
                variety="Сара Бернар",
                country="Нидерланды",
                bloom_season="Весна",
                room_type="Теплица",
                price=12.5,
                supplier_id=rose_house.id,
            )
            flower_2 = self.create_flower(
                name="Садовая роза",
                species="Роза",
                variety="Аваланж",
                country="Эквадор",
                bloom_season="Лето",
                room_type="Теплица",
                price=9.8,
                supplier_id=eco_garden.id,
            )
            flower_3 = self.create_flower(
                name="Элегантный тюльпан",
                species="Тюльпан",
                variety="Роял Вирджин",
                country="Нидерланды",
                bloom_season="Весна",
                room_type="Оранжерея",
                price=6.2,
                supplier_id=urban_bloom.id,
            )
            flower_4 = self.create_flower(
                name="Золотой лютик",
                species="Лютик",
                variety="Элеганс",
                country="Италия",
                bloom_season="Зима",
                room_type="Теплица",
                price=14.0,
                supplier_id=rose_house.id,
            )

            seller_1 = self.create_seller("Petal Point", "Москва, Новый Арбат, 22")
            seller_2 = self.create_seller("Bloom Basket", "Казань, улица Баумана, 17")
            seller_3 = self.create_seller("Flora Loft", "Сочи, Приморская улица, 4")

            self.link_seller_flower(seller_1.id, flower_1.id)
            self.link_seller_flower(seller_1.id, flower_4.id)
            self.link_seller_flower(seller_2.id, flower_2.id)
            self.link_seller_flower(seller_2.id, flower_1.id)
            self.link_seller_flower(seller_3.id, flower_3.id)

            route_1 = self.create_route(
                supplier_id=rose_house.id,
                seller_id=seller_1.id,
                flower_id=flower_1.id,
                quantity=120,
                transport_type="Грузовик",
                planned_date="2026-04-24",
                distance_km=38.0,
                status="created",
            )
            route_2 = self.create_route(
                supplier_id=eco_garden.id,
                seller_id=seller_2.id,
                flower_id=flower_2.id,
                quantity=80,
                transport_type="Рефрижераторный фургон",
                planned_date="2026-04-23",
                distance_km=72.0,
                status="in_transit",
            )
            route_3 = self.create_route(
                supplier_id=urban_bloom.id,
                seller_id=seller_3.id,
                flower_id=flower_3.id,
                quantity=140,
                transport_type="Железнодорожная доставка",
                planned_date="2026-04-20",
                distance_km=455.0,
                status="delivered",
            )

            self.create_task(
                route_id=route_1.id,
                title="Подготовить документы для зоны погрузки",
                assignee="Анна Лебедева",
                due_date="2026-04-23",
                priority="high",
                status="open",
            )
            self.create_task(
                route_id=route_2.id,
                title="Проверить датчики холодовой цепи",
                assignee="Сергей Павлов",
                due_date="2026-04-23",
                priority="critical",
                status="in_progress",
            )
            self.create_task(
                route_id=route_3.id,
                title="Собрать подписанную накладную",
                assignee="Мария Кузнецова",
                due_date="2026-04-21",
                priority="normal",
                status="done",
            )

            self.create_user("manager", "password123", "Иван Петров", "manager", None)
            self.create_user("supplier1", "password123", "Rose House", "supplier", rose_house.id)
            self.create_user("supplier2", "password123", "Eco Garden", "supplier", eco_garden.id)
            self.create_user("seller1", "password123", "Petal Point", "seller", seller_1.id)
            self.create_user("seller2", "password123", "Bloom Basket", "seller", seller_2.id)

    def _ensure_entity_users(self) -> None:
        existing_users = self.list_users()
        existing_entity_ids = {user.entity_id for user in existing_users if user.entity_id is not None}
        existing_usernames = {user.username for user in existing_users}

        for supplier in self.list_suppliers():
            if supplier.id in existing_entity_ids:
                continue
            username = self._default_username("supplier", supplier.id)
            if username in existing_usernames:
                continue
            self.create_user(username, "password123", supplier.full_name, "supplier", supplier.id)
            existing_usernames.add(username)

        for seller in self.list_sellers():
            if seller.id in existing_entity_ids:
                continue
            username = self._default_username("seller", seller.id)
            if username in existing_usernames:
                continue
            self.create_user(username, "password123", seller.full_name, "seller", seller.id)
            existing_usernames.add(username)

    @staticmethod
    def _default_username(prefix: str, entity_id: int) -> str:
        return f"{prefix}{entity_id}"

    @staticmethod
    def _flower_from_row(row: sqlite3.Row) -> Flower:
        return Flower(
            id=row["id"],
            name=row["name"],
            species=row["species"],
            variety=row["variety"],
            country=row["country"],
            bloom_season=row["bloom_season"],
            room_type=row["room_type"],
            price=row["price"],
            supplier_id=row["supplier_id"],
        )

    @staticmethod
    def _supplier_from_row(row: sqlite3.Row) -> Supplier:
        return Supplier(id=row["id"], full_name=row["full_name"], farm_type=row["farm_type"], address=row["address"])

    @staticmethod
    def _seller_from_row(row: sqlite3.Row) -> Seller:
        return Seller(id=row["id"], full_name=row["full_name"], address=row["address"])

    @staticmethod
    def _route_from_row(row: sqlite3.Row) -> DeliveryRoute:
        return DeliveryRoute(
            id=row["id"],
            supplier_id=row["supplier_id"],
            seller_id=row["seller_id"],
            flower_id=row["flower_id"],
            quantity=row["quantity"],
            transport_type=row["transport_type"],
            planned_date=row["planned_date"],
            distance_km=row["distance_km"],
            status=row["status"],
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> LogisticsTask:
        return LogisticsTask(
            id=row["id"],
            route_id=row["route_id"],
            title=row["title"],
            assignee=row["assignee"],
            due_date=row["due_date"],
            priority=row["priority"],
            status=row["status"],
        )

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            password=row["password"],
            role=row["role"],
            full_name=row["full_name"],
            entity_id=row["entity_id"],
        )

    def list_flowers(self) -> list[Flower]:
        rows = self._fetchall("SELECT * FROM flowers ORDER BY name, id")
        return [self._flower_from_row(row) for row in rows]

    def list_suppliers(self) -> list[Supplier]:
        rows = self._fetchall("SELECT * FROM suppliers ORDER BY full_name, id")
        return [self._supplier_from_row(row) for row in rows]

    def list_sellers(self) -> list[Seller]:
        rows = self._fetchall("SELECT * FROM sellers ORDER BY full_name, id")
        return [self._seller_from_row(row) for row in rows]

    def list_routes(self) -> list[DeliveryRoute]:
        rows = self._fetchall("SELECT * FROM routes ORDER BY planned_date DESC, id DESC")
        return [self._route_from_row(row) for row in rows]

    def list_tasks(self) -> list[LogisticsTask]:
        rows = self._fetchall("SELECT * FROM tasks ORDER BY due_date, id")
        return [self._task_from_row(row) for row in rows]

    def create_supplier(self, full_name: str, farm_type: str, address: str) -> Supplier:
        row = self._insert_row("suppliers", ["full_name", "farm_type", "address"], (full_name, farm_type, address))
        return self._supplier_from_row(row)

    def delete_supplier(self, supplier_id: int) -> bool:
        with self._connect() as connection:
            connection.execute(self._sql("DELETE FROM users WHERE role = ? AND entity_id = ?"), ("supplier", supplier_id))
        return self._delete_row("suppliers", "id = ?", (supplier_id,)) > 0

    def create_seller(self, full_name: str, address: str) -> Seller:
        row = self._insert_row("sellers", ["full_name", "address"], (full_name, address))
        return self._seller_from_row(row)

    def delete_seller(self, seller_id: int) -> bool:
        with self._connect() as connection:
            connection.execute(self._sql("DELETE FROM users WHERE role = ? AND entity_id = ?"), ("seller", seller_id))
        return self._delete_row("sellers", "id = ?", (seller_id,)) > 0

    def create_flower(
        self,
        name: str,
        species: str,
        variety: str,
        country: str,
        bloom_season: str,
        room_type: str,
        price: float,
        supplier_id: int,
    ) -> Flower:
        row = self._insert_row(
            "flowers",
            ["name", "species", "variety", "country", "bloom_season", "room_type", "price", "supplier_id"],
            (name, species, variety, country, bloom_season, room_type, price, supplier_id),
        )
        return self._flower_from_row(row)

    def delete_flower(self, flower_id: int) -> bool:
        return self._delete_row("flowers", "id = ?", (flower_id,)) > 0

    def link_seller_flower(self, seller_id: int, flower_id: int) -> None:
        query = (
            "INSERT OR IGNORE INTO seller_flowers (seller_id, flower_id) VALUES (?, ?)"
            if self.backend == "sqlite"
            else "INSERT INTO seller_flowers (seller_id, flower_id) VALUES (?, ?) ON CONFLICT DO NOTHING"
        )
        with self._connect() as connection:
            connection.execute(self._sql(query), (seller_id, flower_id))

    def unlink_seller_flower(self, seller_id: int, flower_id: int) -> bool:
        return self._delete_row("seller_flowers", "seller_id = ? AND flower_id = ?", (seller_id, flower_id)) > 0

    def get_supplier(self, supplier_id: int) -> Supplier | None:
        row = self._fetchone("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
        return self._supplier_from_row(row) if row else None

    def get_seller(self, seller_id: int) -> Seller | None:
        row = self._fetchone("SELECT * FROM sellers WHERE id = ?", (seller_id,))
        return self._seller_from_row(row) if row else None

    def get_flower(self, flower_id: int) -> Flower | None:
        row = self._fetchone("SELECT * FROM flowers WHERE id = ?", (flower_id,))
        return self._flower_from_row(row) if row else None

    def get_flowers_by_ids(self, flower_ids: Iterable[int]) -> list[Flower]:
        ids = list(dict.fromkeys(flower_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        query = f"SELECT * FROM flowers WHERE id IN ({placeholders}) ORDER BY name, id"
        rows = self._fetchall(query, tuple(ids))
        return [self._flower_from_row(row) for row in rows]

    def create_route(
        self,
        supplier_id: int,
        seller_id: int,
        flower_id: int,
        quantity: int,
        transport_type: str,
        planned_date: str,
        distance_km: float,
        status: str = "created",
    ) -> DeliveryRoute:
        row = self._insert_row(
            "routes",
            ["supplier_id", "seller_id", "flower_id", "quantity", "transport_type", "planned_date", "distance_km", "status"],
            (supplier_id, seller_id, flower_id, quantity, transport_type, planned_date, distance_km, status),
        )
        return self._route_from_row(row)

    def get_route(self, route_id: int) -> DeliveryRoute | None:
        row = self._fetchone("SELECT * FROM routes WHERE id = ?", (route_id,))
        return self._route_from_row(row) if row else None

    def update_route_status(self, route_id: int, status: str) -> bool:
        return self._update_row("routes", "status = ?", (status,), "id = ?", (route_id,)) > 0

    def create_task(
        self,
        route_id: int,
        title: str,
        assignee: str,
        due_date: str,
        priority: str,
        status: str = "open",
    ) -> LogisticsTask:
        row = self._insert_row(
            "tasks",
            ["route_id", "title", "assignee", "due_date", "priority", "status"],
            (route_id, title, assignee, due_date, priority, status),
        )
        return self._task_from_row(row)

    def get_task(self, task_id: int) -> LogisticsTask | None:
        row = self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return self._task_from_row(row) if row else None

    def update_task_status(self, task_id: int, status: str) -> bool:
        return self._update_row("tasks", "status = ?", (status,), "id = ?", (task_id,)) > 0

    def delete_task(self, task_id: int) -> bool:
        return self._delete_row("tasks", "id = ?", (task_id,)) > 0

    def create_user(
        self,
        username: str,
        password: str,
        full_name: str,
        role: str,
        entity_id: int | None,
    ) -> User:
        row = self._insert_row(
            "users",
            ["username", "password", "role", "full_name", "entity_id"],
            (username, password, role, full_name, entity_id),
        )
        return self._user_from_row(row)

    def get_user_by_username(self, username: str) -> User | None:
        row = self._fetchone("SELECT * FROM users WHERE username = ?", (username,))
        return self._user_from_row(row) if row else None

    def list_users(self) -> list[User]:
        rows = self._fetchall("SELECT * FROM users ORDER BY username, id")
        return [self._user_from_row(row) for row in rows]
