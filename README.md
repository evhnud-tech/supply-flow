# SupplyFlow

SupplyFlow is a multi-page web app for supply tracking: routes, logistics tasks, and delivery status control.

## Stack

- Backend: FastAPI
- Frontend: Jinja templates + custom CSS
- Storage: SQLite by default, PostgreSQL when `DATABASE_URL` is set
- PostgreSQL is the recommended option if you want to edit the DB from Docker or DataGrip

## Functional blocks

- Catalog of products used in deliveries (`/flowers`)
- Suppliers and receivers (`/suppliers`, `/sellers`)
- Delivery route creation and status tracking (`/routes`)
- Logistics task board and completed deliveries report (`/analytics`)

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open: http://127.0.0.1:8000

## Screenshots for report

After launching the app, use these pages for report screenshots:

- Login page: `http://127.0.0.1:8000/login`
- Home dashboard: `http://127.0.0.1:8000/`
- Flowers catalog and filters: `http://127.0.0.1:8000/flowers`
- Suppliers: `http://127.0.0.1:8000/suppliers`
- Sellers and "search sellers by variety": `http://127.0.0.1:8000/sellers`
- Routes and status updates: `http://127.0.0.1:8000/routes`
- Analytics, task board, completed deliveries report: `http://127.0.0.1:8000/analytics`
- Interface layout page: `http://127.0.0.1:8000/layout`
- Swagger UI (OpenAPI docs): `http://127.0.0.1:8000/docs`

For API screenshot examples in Swagger, use endpoint:

- `GET /api/sellers/by-variety?variety=<value>`

The local SQLite database file is created automatically on first run and seeded with demo data.

## PostgreSQL / Docker

Start a local Postgres container:

```bash
docker compose up -d db
```

If you changed `POSTGRES_USER` or `POSTGRES_PASSWORD` after the first start, recreate the data volume first. Postgres keeps the old credentials inside the existing volume:

```bash
docker compose down -v
docker compose up -d db
```

Then set `DATABASE_URL` to:

```text
postgresql://supplyflow:supplyflow@localhost:5432/supplyflow
```

After that, run the app normally. The tables are created automatically on first start, and DataGrip can connect to the same host, port, database, and credentials.
