"""Authenticated tenant privacy API backed by the SQL unit of work."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.persistence.privacy import RetentionPolicy, SqlPrivacyRepository
from app.persistence.runtime import get_persistence

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


class RetentionPolicyRequest(BaseModel):
    scan_retention_days: int = Field(365, ge=0)
    audit_retention_days: int = Field(365, ge=0)
    export_retention_days: int = Field(7, ge=0)
    backup_retention_days: int = Field(30, ge=0)
    deletion_recovery_days: int = Field(7, ge=0, le=30)
    backup_deletion_lag_days: int = Field(30, ge=0)


def _privacy() -> SqlPrivacyRepository:
    persistence = get_persistence()
    if persistence is None:
        raise HTTPException(status_code=503, detail="Transactional persistence is required")
    return persistence.privacy


@router.get("/retention")
async def get_retention() -> dict[str, Any]:
    return asdict(_privacy().get_retention_policy())


@router.put("/retention")
async def put_retention(request: RetentionPolicyRequest) -> dict[str, Any]:
    policy = RetentionPolicy(**request.model_dump())
    return asdict(_privacy().set_retention_policy(policy))


@router.post("/exports", status_code=202)
async def create_export() -> dict[str, Any]:
    return asdict(_privacy().create_export_job())


@router.get("/exports/{job_id}")
async def get_export(job_id: str) -> dict[str, Any]:
    job = _privacy().get_export_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    return asdict(job)


@router.get("/exports/{job_id}/archive")
async def get_export_archive(job_id: str) -> dict[str, str]:
    archive = _privacy().get_export_archive(job_id)
    if archive is None:
        raise HTTPException(status_code=404, detail="Completed export archive not found")
    return {"archive": archive}


@router.post("/deletion-requests", status_code=202)
async def request_deletion() -> dict[str, Any]:
    return asdict(_privacy().request_deletion())


@router.get("/deletion-requests/current")
async def deletion_state() -> dict[str, Any]:
    return asdict(_privacy().get_deletion_state())
