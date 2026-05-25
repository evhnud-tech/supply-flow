from __future__ import annotations

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
    supplier_id: int | None = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    flowers = service.find_flowers(season, country, variety, supplier_id)
    filters = service.flower_filters()
    can_add = check_role(user, ["manager", "supplier"])
    
    return templates.TemplateResponse(
        request,
        "flowers.html",
        {
            "user": user,
            "active_page": "flowers",
            "flowers": flowers,
            "suppliers": repo.list_suppliers(),
            "filters": filters,
            "can_add": can_add,
            "form": {
                "season": season or "",
                "country": country or "",
                "variety": variety or "",
                "supplier_id": supplier_id or "",
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
    
    if not repo.get_supplier(supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    repo.create_flower(name, species, variety, country, bloom_season, room_type, price, supplier_id)
    return RedirectResponse(url="/flowers", status_code=303)


@app.post("/flowers/{flower_id}/delete")
def delete_flower(request: Request, flower_id: int):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager", "supplier"]):
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
        },
    )


@app.post("/suppliers")
def add_supplier(
    request: Request,
    full_name: str = Form(...),
    farm_type: str = Form(...),
    address: str = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager"]):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    repo.create_supplier(full_name, farm_type, address)
    return RedirectResponse(url="/suppliers", status_code=303)


@app.get("/sellers")
def sellers_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    can_manage = check_role(user, ["manager"])
    
    return templates.TemplateResponse(
        request,
        "sellers.html",
        {
            "user": user,
            "active_page": "sellers",
            "seller_rows": service.seller_overview(),
            "can_manage": can_manage,
        },
    )


@app.post("/sellers")
def add_seller(
    request: Request,
    full_name: str = Form(...),
    address: str = Form(...),
):
    user = get_current_user(request)
    if not user or not check_role(user, ["manager"]):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    repo.create_seller(full_name, address)
    return RedirectResponse(url="/sellers", status_code=303)


@app.get("/routes")
def routes_page(
    request: Request,
    status: str | None = None,
    supplier_id: int | None = None,
    seller_id: int | None = None,
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    can_create = check_role(user, ["manager", "supplier"])
    supplier_scope = own_supplier_id(user)
    seller_scope = own_seller_id(user)
    if user["role"] == "supplier":
        supplier_id = supplier_id or supplier_scope
    elif user["role"] == "seller":
        seller_id = seller_id or seller_scope

    route_rows = service.route_overview(status, supplier_id, seller_id)
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
                "supplier_id": supplier_id or "",
                "seller_id": seller_id or "",
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
    if not repo.update_route_status(route_id, status):
        raise HTTPException(status_code=404, detail="Route not found")
    return RedirectResponse(url="/routes", status_code=303)


@app.get("/analytics")
def analytics_page(
    request: Request,
    seller_a_id: int | None = None,
    seller_b_id: int | None = None,
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
        if seller_a_id and seller_b_id and seller_a_id != seller_b_id:
            common_suppliers = service.shared_suppliers(seller_a_id, seller_b_id)

    routes_for_task_form = route_items if can_create_task else []

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
            "seller_a_id": seller_a_id or "",
            "seller_b_id": seller_b_id or "",
            "form": {
                "task_status": task_status or "",
                "priority": priority or "",
            },
            "can_create_task": can_create_task,
            "can_compare_suppliers": can_compare_suppliers,
        },
    )
def add_task(
    route_id: int = Form(...),
    title: str = Form(...),
    assignee: str = Form(...),
    due_date: str = Form(...),
    priority: str = Form(...),
):
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
    task_id: int,
    status: str = Form(...),
):
    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported status")
    if not repo.update_task_status(task_id, status):
        raise HTTPException(status_code=404, detail="Task not found")
    return RedirectResponse(url="/analytics", status_code=303)
