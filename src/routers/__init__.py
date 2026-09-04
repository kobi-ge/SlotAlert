from src.routers.auth import router as auth_router
from src.routers.business import router as business_router
from src.routers.public import router as public_router
from src.routers.slots import router as slots_router
from src.routers.webhooks import router as webhooks_router

__all__ = ["slots_router", "webhooks_router", "public_router", "business_router", "auth_router"]
