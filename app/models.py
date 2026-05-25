from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Flower:
    id: int
    name: str
    species: str
    variety: str
    country: str
    bloom_season: str
    room_type: str
    price: float
    supplier_id: int


@dataclass(slots=True)
class Supplier:
    id: int
    full_name: str
    farm_type: str
    address: str


@dataclass(slots=True)
class Seller:
    id: int
    full_name: str
    address: str


@dataclass(slots=True)
class SellerFlower:
    seller_id: int
    flower_id: int


@dataclass(slots=True)
class DeliveryRoute:
    id: int
    supplier_id: int
    seller_id: int
    flower_id: int
    quantity: int
    transport_type: str
    planned_date: str
    distance_km: float
    status: str


@dataclass(slots=True)
class LogisticsTask:
    id: int
    route_id: int
    title: str
    assignee: str
    due_date: str
    priority: str
    status: str


@dataclass(slots=True)
class User:
    id: int
    username: str
    password: str
    role: str  # "manager", "supplier", "seller"
    full_name: str
    entity_id: int | None = None  # supplier_id или seller_id если не менеджер
