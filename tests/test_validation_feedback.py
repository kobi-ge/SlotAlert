import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_backend_validation_returns_hebrew_field_errors_on_bad_phone(client: httpx.AsyncClient):
    """Verify backend RequestValidationError maps phone_number to friendly Hebrew message."""
    payload = {
        "name": "קליניקה לבדיקה",
        "phone_number": "not-a-phone",
        "business_type": "clinic",
        "services": [{"name": "טיפול", "duration_minutes": 30, "price": 100.0}],
    }
    res = await client.post("/api/v1/public/register-business", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "field_errors" in data
    assert "phone_number" in data["field_errors"]
    assert "מספר הטלפון הנייד אינו תקין" in data["field_errors"]["phone_number"]


@pytest.mark.asyncio
async def test_backend_validation_returns_hebrew_field_errors_on_short_name(client: httpx.AsyncClient):
    """Verify backend RequestValidationError maps short name to friendly Hebrew message."""
    payload = {
        "name": "א",  # Less than 2 chars
        "phone_number": "050-1234567",
        "business_type": "clinic",
        "services": [{"name": "טיפול", "duration_minutes": 30, "price": 100.0}],
    }
    res = await client.post("/api/v1/public/register-business", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "field_errors" in data
    assert "name" in data["field_errors"]
    assert "לפחות 2 תווים" in data["field_errors"]["name"]


@pytest.mark.asyncio
async def test_backend_validation_returns_hebrew_field_errors_on_empty_services(client: httpx.AsyncClient):
    """Verify backend RequestValidationError maps empty services to friendly Hebrew message."""
    payload = {
        "name": "קליניקה ללא שירותים",
        "phone_number": "050-1234567",
        "business_type": "clinic",
        "services": [],
    }
    res = await client.post("/api/v1/public/register-business", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "field_errors" in data
    assert "services" in data["field_errors"]
    assert "לפחות שירות אחד" in data["field_errors"]["services"]


@pytest.mark.asyncio
async def test_backend_validation_on_customer_optin_bad_inputs(client: httpx.AsyncClient):
    """Verify customer optin endpoint returns Hebrew field errors on invalid inputs."""
    payload = {
        "full_name": "ד",  # Too short
        "phone_number": "03-1234567",  # Landline
        "service_ids": [],
        "days_of_week": [0],
        "time_slots": ["MORNING"],
    }
    res = await client.post("/api/v1/public/b/non-existent-biz/register", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "field_errors" in data
    assert "phone_number" in data["field_errors"]
    assert "full_name" in data["field_errors"]
