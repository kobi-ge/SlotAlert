from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = Field(..., description="Overall system status (ok / degraded / error)")
    db: str = Field(..., description="PostgreSQL database connectivity status")
    redis: str = Field(..., description="Redis cache connectivity status")
