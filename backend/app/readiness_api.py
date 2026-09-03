"""Authenticated operator readiness endpoint."""

from fastapi import APIRouter, Response, status

from app.readiness import assess_readiness

router = APIRouter(prefix="/api/ops", tags=["operations"])


@router.get("/readiness")
async def readiness(response: Response) -> dict[str, object]:
    report = assess_readiness()
    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report.to_dict()
