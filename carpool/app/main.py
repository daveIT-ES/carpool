"""Aplicación FastAPI: reparto de gastos de coche compartido."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import init_db
from .deps import render
from .routers import admin, auth, geo, trips

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="carpool_session",
    https_only=settings.cookie_secure,
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(trips.router)
app.include_router(geo.router)
app.include_router(admin.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    destino = exc.headers.get("Location") if exc.headers else None
    if destino:
        return RedirectResponse(destino, status_code=303)
    if request.headers.get("accept", "").startswith("text/html"):
        return render(
            request,
            "error.html",
            codigo=exc.status_code,
            mensaje=exc.detail,
            user=None,
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
