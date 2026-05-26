from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .repository import InMemoryRepository
from .services import (
    LogisticsService,
    ROUTE_STATUSES,
    ROUTE_STATUS_LABELS,
    TASK_PRIORITIES,
    TASK_PRIORITY_LABELS,
    TASK_STATUSES,
    TASK_STATUS_LABELS,
)

app = FastAPI(title="SupplyFlow")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(
    route_status_labels=ROUTE_STATUS_LABELS,
    task_status_labels=TASK_STATUS_LABELS,
    task_priority_labels=TASK_PRIORITY_LABELS,
)


def format_date_ru(value: str) -> str:
    from datetime import datetime

    return datetime.fromisoformat(value).strftime("%d.%m.%Y")


templates.env.globals.update(format_date_ru=format_date_ru)


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_file(Path(__file__).resolve().parent.parent / ".env")

repo = InMemoryRepository()
service = LogisticsService(repo)


def get_current_user(request: Request) -> dict | None:
    """Get current user from session cookie"""
    username = request.cookies.get("username")
    if not username:
        return None
    user = repo.get_user_by_username(username)
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
        "entity_id": user.entity_id,
    }


def require_login(request: Request) -> None:
    """Redirect to login if not authenticated"""
    if not get_current_user(request):
        raise HTTPException(status_code=403, detail="Not authenticated")


def check_role(user: dict, required_roles: list[str]) -> bool:
    """Check if user has required role"""
    return user["role"] in required_roles if user else False


def parse_int_query(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid integer filter value")


def own_supplier_id(user: dict) -> int | None:
    return user.get("entity_id") if user and user.get("role") == "supplier" else None


def own_seller_id(user: dict) -> int | None:
    return user.get("entity_id") if user and user.get("role") == "seller" else None


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = repo.get_user_by_username(username)
    if not user or user.password != password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Неверное имя пользователя или пароль"},
            status_code=401,
        )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("username", username, max_age=86400)  # 24 hours
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("username")
    return response


@app.get("/")
def home(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "active_page": "home",
            "stats": service.logistics_kpis(),
            "top_sellers": service.sellers_with_most_routes()[:4],
        },
    )


@app.get("/layout")
def layout_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "layout.html",
        {
            "user": user,
            "active_page": "layout",
            "stats": service.logistics_kpis(),
        },
    )


@app.get("/flowers")
def flowers_page(
    request: Request,
    season: str | None = None,
    country: str | None = None,
    variety: str | None = None,
    supplier_id: str | None = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    supplier_scope = own_supplier_id(user)
    supplier_id_value = parse_int_query(supplier_id)
    if supplier_scope is not None:
        supplier_id_value = supplier_scope

    flowers = service.find_flowers(season, country, variety, supplier_id_value)
    filters = service.flower_filters()
    can_add = check_role(user, ["manager", "supplier"])
    suppliers = (
        [repo.get_supplier(supplier_scope)]
        if supplier_scope and repo.get_supplier(supplier_scope)
        else repo.list_suppliers()
    )
    
    return templates.TemplateResponse(
        request,
        "flowers.html",
        {
            "user": user,
            "active_page": "flowers",
            "flowers": flowers,
            "suppliers": suppliers,
            "filters": filters,
            "can_add": can_add,
            "supplier_scope": supplier_scope,
            "form": {
                "season": season or "",
                "country": country or "",
                "variety": variety or "",
                "supplier_id": supplier_id_value or "",
            },
        },
    )


@app.post("/flowers")
def add_flower(
    request: Request,
    name: str = Form(...),
    species: str = Form(...),
    variety: str = Form(...),
    country: str = Form(...),
    bloom_season: str = Form(...),
    room_type: str = Form(...),
    price: float = Form(...),
    supplier_id: int = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    supplier_scope = own_supplier_id(user)
    if supplier_scope is not None:
        supplier_id = supplier_scope
    
    if not repo.get_supplier(supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    repo.create_flower(name, species, variety, country, bloom_season, room_type, price, supplier_id)
    return RedirectResponse(url="/flowers", status_code=303)


@app.post("/flowers/{flower_id}/delete")
def delete_flower(request: Request, flower_id: int):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    supplier_scope = own_supplier_id(user)
    flower = repo.get_flower(flower_id)
    if not flower:
        raise HTTPException(status_code=404, detail="Flower not found")
    if supplier_scope is not None and flower.supplier_id != supplier_scope:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    repo.delete_flower(flower_id)
    return RedirectResponse(url="/flowers", status_code=303)


@app.get("/suppliers")
def suppliers_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    can_manage = check_role(user, ["manager"])
    
    return templates.TemplateResponse(
        request,
        "suppliers.html",
        {
            "user": user,
            "active_page": "suppliers",
            "supplier_rows": service.supplier_overview(),
            "can_manage": can_manage,
            "can_delete": can_manage,
        },
    )


@app.post("/suppliers")
def add_supplier(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    farm_type: str = Form(...),
    address: str = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    if repo.get_user_by_username(username):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    supplier = repo.create_supplier(full_name, farm_type, address)
    repo.create_user(username, password, full_name, "supplier", supplier.id)
    return RedirectResponse(url="/suppliers", status_code=303)


@app.post("/suppliers/{supplier_id}/delete")
def delete_supplier(request: Request, supplier_id: int):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not repo.delete_supplier(supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    return RedirectResponse(url="/suppliers", status_code=303)


@app.get("/sellers")
def sellers_page(request: Request, variety: str | None = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    can_manage = check_role(user, ["manager"])
    variety_query = (variety or "").strip()
    matched_rows = service.sellers_by_variety(variety_query) if variety_query else []
    
    return templates.TemplateResponse(
        request,
        "sellers.html",
        {
            "user": user,
            "active_page": "sellers",
            "seller_rows": service.seller_overview(),
            "matched_rows": matched_rows,
            "variety_query": variety_query,
            "can_manage": can_manage,
            "can_delete": can_manage,
        },
    )


@app.post("/sellers")
def add_seller(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    address: str = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    if repo.get_user_by_username(username):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    seller = repo.create_seller(full_name, address)
    repo.create_user(username, password, full_name, "seller", seller.id)
    return RedirectResponse(url="/sellers", status_code=303)


@app.post("/sellers/{seller_id}/delete")
def delete_seller(request: Request, seller_id: int):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not repo.delete_seller(seller_id):
        raise HTTPException(status_code=404, detail="Seller not found")
    return RedirectResponse(url="/sellers", status_code=303)


@app.get("/routes")
def routes_page(
    request: Request,
    status: str | None = None,
    supplier_id: str | None = None,
    seller_id: str | None = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    can_create = check_role(user, ["manager", "supplier"])
    supplier_scope = own_supplier_id(user)
    seller_scope = own_seller_id(user)
    supplier_id_value = parse_int_query(supplier_id)
    seller_id_value = parse_int_query(seller_id)
    if user["role"] == "supplier":
        supplier_id_value = supplier_id_value or supplier_scope
    elif user["role"] == "seller":
        seller_id_value = seller_id_value or seller_scope

    route_rows = service.route_overview(status, supplier_id_value, seller_id_value)
    return templates.TemplateResponse(
        request,
        "routes.html",
        {
            "user": user,
            "active_page": "routes",
            "route_rows": route_rows,
            "statuses": ROUTE_STATUSES,
            "suppliers": [repo.get_supplier(supplier_scope)] if supplier_scope and repo.get_supplier(supplier_scope) else repo.list_suppliers(),
            "sellers": [repo.get_seller(seller_scope)] if seller_scope and repo.get_seller(seller_scope) else repo.list_sellers(),
            "flowers": [flower for flower in repo.list_flowers() if not supplier_scope or flower.supplier_id == supplier_scope],
            "can_create": can_create,
            "supplier_scope": supplier_scope,
            "form": {
                "status": status or "",
                "supplier_id": supplier_id_value or "",
                "seller_id": seller_id_value or "",
            },
        },
    )


@app.post("/routes")
def add_route(
    request: Request,
    supplier_id: int = Form(...),
    seller_id: int = Form(...),
    flower_id: int = Form(...),
    quantity: int = Form(...),
    transport_type: str = Form(...),
    planned_date: str = Form(...),
    distance_km: float = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    supplier_scope = own_supplier_id(user)
    if user["role"] == "supplier":
        if supplier_scope is None:
            raise HTTPException(status_code=403, detail="Forbidden")
        supplier_id = supplier_scope
    
    if not repo.get_supplier(supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not repo.get_seller(seller_id):
        raise HTTPException(status_code=404, detail="Seller not found")
    if not repo.get_flower(flower_id):
        raise HTTPException(status_code=404, detail="Flower not found")

    repo.create_route(
        supplier_id=supplier_id,
        seller_id=seller_id,
        flower_id=flower_id,
        quantity=quantity,
        transport_type=transport_type,
        planned_date=planned_date,
        distance_km=distance_km,
    )
    return RedirectResponse(url="/routes", status_code=303)


@app.post("/routes/{route_id}/status")
def update_route_status(
    request: Request,
    route_id: int,
    status: str = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier", "seller"]):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    if status not in ROUTE_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported status")
    route = repo.get_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    supplier_scope = own_supplier_id(user)
    seller_scope = own_seller_id(user)
    if supplier_scope is not None and route.supplier_id != supplier_scope:
        raise HTTPException(status_code=403, detail="Forbidden")
    if seller_scope is not None and route.seller_id != seller_scope:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not repo.update_route_status(route_id, status):
        raise HTTPException(status_code=404, detail="Route not found")
    return RedirectResponse(url="/routes", status_code=303)


@app.get("/analytics")
def analytics_page(
    request: Request,
    seller_a_id: str | None = None,
    seller_b_id: str | None = None,
    task_status: str | None = None,
    priority: str | None = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    supplier_scope = own_supplier_id(user)
    seller_scope = own_seller_id(user)
    can_compare_suppliers = user["role"] == "manager"
    can_create_task = user["role"] in {"manager", "supplier"}
    seller_a_value = parse_int_query(seller_a_id)
    seller_b_value = parse_int_query(seller_b_id)

    if user["role"] == "supplier":
        route_items = [route for route in repo.list_routes() if route.supplier_id == supplier_scope]
        sellers = [seller for seller in repo.list_sellers() if any(route.seller_id == seller.id for route in route_items)]
        task_rows = [row for row in service.task_board(task_status, priority) if row["route"].supplier_id == supplier_scope]
        report_rows = [row for row in service.completed_deliveries_report() if row["route"].supplier_id == supplier_scope]
        common_suppliers: list[object] = []
    elif user["role"] == "seller":
        route_items = [route for route in repo.list_routes() if route.seller_id == seller_scope]
        sellers = [seller for seller in repo.list_sellers() if seller.id == seller_scope]
        task_rows = [row for row in service.task_board(task_status, priority) if row["route"].seller_id == seller_scope]
        report_rows = [row for row in service.completed_deliveries_report() if row["route"].seller_id == seller_scope]
        common_suppliers = []
    else:
        route_items = repo.list_routes()
        sellers = repo.list_sellers()
        task_rows = service.task_board(task_status, priority)
        report_rows = service.completed_deliveries_report()
        common_suppliers = []
        if seller_a_value and seller_b_value and seller_a_value != seller_b_value:
            common_suppliers = service.shared_suppliers(seller_a_value, seller_b_value)

    routes_for_task_form: list[dict[str, object]] = []
    if can_create_task:
        for route in route_items:
            supplier = repo.get_supplier(route.supplier_id)
            seller = repo.get_seller(route.seller_id)
            flower = repo.get_flower(route.flower_id)
            if not supplier or not seller or not flower:
                continue
            routes_for_task_form.append(
                {
                    "route": route,
                    "supplier": supplier,
                    "seller": seller,
                    "flower": flower,
                }
            )

    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "user": user,
            "active_page": "analytics",
            "task_rows": task_rows,
            "report_rows": report_rows,
            "statuses": TASK_STATUSES,
            "priorities": TASK_PRIORITIES,
            "route_statuses": ROUTE_STATUSES,
            "routes": routes_for_task_form,
            "sellers": sellers,
            "common_suppliers": common_suppliers,
            "seller_a_id": seller_a_value or "",
            "seller_b_id": seller_b_value or "",
            "form": {
                "task_status": task_status or "",
                "priority": priority or "",
            },
            "can_create_task": can_create_task,
            "can_compare_suppliers": can_compare_suppliers,
        },
    )
@app.post("/analytics/tasks")
def add_task(
    request: Request,
    route_id: int = Form(...),
    title: str = Form(...),
    assignee: str = Form(...),
    due_date: str = Form(...),
    priority: str = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not repo.get_route(route_id):
        raise HTTPException(status_code=404, detail="Route not found")
    if priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Unsupported priority")

    repo.create_task(
        route_id=route_id,
        title=title,
        assignee=assignee,
        due_date=due_date,
        priority=priority,
    )
    return RedirectResponse(url="/analytics", status_code=303)


@app.post("/analytics/tasks/{task_id}/status")
def update_task_status(
    request: Request,
    task_id: int,
    status: str = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier", "seller"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported status")

    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    route = repo.get_route(task.route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    supplier_scope = own_supplier_id(user)
    seller_scope = own_seller_id(user)
    if supplier_scope is not None and route.supplier_id != supplier_scope:
        raise HTTPException(status_code=403, detail="Forbidden")
    if seller_scope is not None and route.seller_id != seller_scope:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not repo.update_task_status(task_id, status):
        raise HTTPException(status_code=404, detail="Task not found")
    return RedirectResponse(url="/analytics", status_code=303)


@app.get("/api/sellers/by-variety", tags=["Analytics API"])
def api_sellers_by_variety(variety: str):
    """JSON endpoint for searching sellers by flower variety (for Swagger/docs and integration)."""
    variety_query = variety.strip()
    if not variety_query:
        raise HTTPException(status_code=400, detail="Query parameter 'variety' is required")

    rows = service.sellers_by_variety(variety_query)
    return {
        "variety": variety_query,
        "count": len(rows),
        "items": [
            {
                "seller": {
                    "id": row["seller"].id,
                    "full_name": row["seller"].full_name,
                    "address": row["seller"].address,
                },
                "flowers": [
                    {
                        "id": flower.id,
                        "name": flower.name,
                        "variety": flower.variety,
                    }
                    for flower in row["flowers"]
                ],
            }
            for row in rows
        ],
    }


@app.post("/analytics/tasks/{task_id}/delete")
def delete_task(
    request: Request,
    task_id: int,
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not repo.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return RedirectResponse(url="/analytics", status_code=303)
