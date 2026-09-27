"""FastAPI application entry."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import bootstrap, cart, catalog, events, guide, internal, mercury
from app.core.database import init_db
from app.core.errors import AppError

ROOT_DIR = Path(__file__).resolve().parents[2]
IMAGES_DIR = ROOT_DIR / "data" / "images"

app = FastAPI(title="Sale-guide API", version="0.1.0")

if IMAGES_DIR.is_dir():
    app.mount("/media/images", StaticFiles(directory=str(IMAGES_DIR)), name="product_images")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bootstrap.router)
app.include_router(catalog.router)
app.include_router(cart.router)
app.include_router(guide.router)
app.include_router(mercury.router)
app.include_router(events.router)
app.include_router(internal.router)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(exc),
                "retryable": True,
            }
        },
    )


@app.on_event("startup")
def on_startup():
    init_db()


def create_app() -> FastAPI:
    return app
