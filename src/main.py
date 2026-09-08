import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.database.connection import close_redis_client, get_db, get_redis_client
from src.routers.auth import router as auth_router
from src.routers.business import router as business_router
from src.routers.public import router as public_router
from src.routers.slots import router as slots_router
from src.routers.webhooks import router as webhooks_router
from src.schemas.health import HealthResponse
from src.tasks.queue import task_queue
# Ensure tasks are registered
import src.tasks.broadcast_tasks  # noqa: F401
import src.tasks.webhook_tasks  # noqa: F401

settings = get_settings()
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown routines."""
    # Startup: ensure redis connection pool is ready and start queue worker
    _ = get_redis_client()
    task_queue.start_worker()
    yield
    # Shutdown: gracefully close worker and redis connections
    await task_queue.stop_worker()
    await close_redis_client()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="SlotAlert (תור פנוי) - Micro-SaaS platform for last-minute appointment cancellation alerts via WhatsApp.",
    version="1.0.0",
    lifespan=lifespan,
)


from fastapi.encoders import jsonable_encoder

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Log 422 validation errors with full field details and Hebrew mapping."""
    errors = exc.errors()
    formatted = []
    field_errors = {}

    for err in errors:
        loc_parts = err.get("loc", [])
        loc = " -> ".join(str(l) for l in loc_parts)
        field_name = str(loc_parts[-1]) if loc_parts else ""
        msg = err.get("msg", "")
        inp = err.get("input", "")
        formatted.append(f"[{loc}]: {msg} (input: {inp!r})")

        # Map to friendly Hebrew field-level guidance
        if field_name == "phone_number":
            field_errors["phone_number"] = "מספר הטלפון הנייד אינו תקין (נדרש מספר נייד ישראלי, למשל 050-1234567)"
        elif field_name in ("name", "full_name"):
            field_errors[field_name] = "השם קצר מדי, נא להזין לפחות 2 תווים"
        elif field_name == "services":
            field_errors["services"] = "יש להגדיר לפחות שירות אחד תקין בקטלוג"
        elif field_name == "duration_minutes":
            field_errors["duration_minutes"] = "משך הטיפול חייב להיות לפחות 5 דקות"
        elif field_name in ("price", "custom_price"):
            field_errors[field_name] = "מחיר הטיפול חייב להיות מספר לא שלילי"
        elif field_name == "custom_service_name":
            field_errors["custom_service_name"] = "נא לתת שם לשירות המותאם אישית"
    
    error_summary = "; ".join(formatted)
    logger.warning(f"⚠️ [422 Validation Error] {request.method} {request.url.path} - {error_summary}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": jsonable_encoder(errors),
            "message": error_summary,
            "field_errors": field_errors,
        },
    )



# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(slots_router, prefix=settings.API_V1_STR)
app.include_router(webhooks_router, prefix=settings.API_V1_STR)
app.include_router(webhooks_router)  # also mount at root /webhooks/whatsapp
app.include_router(public_router)
app.include_router(business_router)
app.include_router(auth_router, prefix=settings.API_V1_STR)

# Mount Static Files for PWA & Landing Page
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

from fastapi.responses import FileResponse

@app.get("/login/{slug}", include_in_schema=False)
async def login_page(slug: str):
    login_path = os.path.join(static_dir, "login.html")
    return FileResponse(login_path, media_type="text/html")


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
    description="Pings PostgreSQL and Redis and returns their operational connectivity status.",
)
async def health_check(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Check database and Redis connectivity."""
    db_status = "connected"
    redis_status = "connected"

    # Ping PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {str(exc)}"

    # Ping Redis
    try:
        redis = get_redis_client()
        pong = await redis.ping()
        if not pong:
            redis_status = "error: ping returned false"
    except Exception as exc:
        redis_status = f"error: {str(exc)}"

    is_healthy = (db_status == "connected") and (redis_status == "connected")
    overall_status = "ok" if is_healthy else "degraded"
    status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "db": db_status,
            "redis": redis_status,
        },
    )


@app.get("/", tags=["Landing Page"])
async def root():
    """Serve the public SaaS marketing & onboarding landing page."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return {
        "service": settings.PROJECT_NAME,
        "environment": settings.APP_ENV,
        "docs_url": "/docs",
        "health_url": "/health",
    }

