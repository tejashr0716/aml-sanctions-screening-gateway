import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Request, Response, Query, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from src.config import settings
from src.database import db
from src.sync import sync_service
from src.screener import screener
from src.models import (
    ScreeningRequest,
    ScreeningResult,
    BatchScreeningRequest,
    BatchScreeningResult,
    AuditEntry,
    SyncResponse,
    HealthResponse
)

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger("aml_gateway")


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        corr_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = corr_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = corr_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist
    db.init_sync_db()
    count = await db.get_total_entities_count()
    if count == 0:
        logger.info("Database empty, initiating initial sanctions sync from live UN feed...")
        try:
            await sync_service.sync_now()
        except Exception as e:
            logger.warning("Initial live sync deferred or failed: %s", e)
    await screener.reload_cache()
    logger.info("AML Sanctions Screening Gateway ready with %d entities cached.", len(screener._cache))
    yield
    # Shutdown logic if any


app = FastAPI(
    title="AML Sanctions Screening Gateway",
    description="High-performance, multi-tier AML & KYC sanctions screening gateway against live United Nations Consolidated Sanctions.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    try:
        count = await db.get_total_entities_count()
        last_sync = await db.get_last_sync_timestamp()
        return HealthResponse(
            status="HEALTHY",
            database_status="CONNECTED",
            total_entities_indexed=count,
            last_sync_timestamp=last_sync
        )
    except Exception as e:
        return HealthResponse(
            status="DEGRADED",
            database_status=f"ERROR: {str(e)}",
            total_entities_indexed=0,
            last_sync_timestamp=None
        )


@app.post("/api/sanctions/sync", response_model=SyncResponse)
async def trigger_sync():
    try:
        result = await sync_service.sync_now()
        await screener.reload_cache()
        return SyncResponse(
            status=result["status"],
            total_individuals=result["total_individuals"],
            total_entities=result["total_entities"],
            synced_at=result["synced_at"],
            duration_seconds=result["duration_seconds"]
        )
    except Exception as e:
        logger.error("Failed to sync sanctions list: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sanctions feed synchronization failed: {str(e)}"
        )


@app.post("/api/screen/entity", response_model=ScreeningResult)
async def screen_single_entity(payload: ScreeningRequest, request: Request):
    req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    result = await screener.screen_entity(payload, request_id=req_id)
    return result


@app.post("/api/screen/batch", response_model=BatchScreeningResult)
async def screen_batch_entities(payload: BatchScreeningRequest, request: Request):
    req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    result = await screener.screen_batch(payload, request_id=req_id)
    return result


@app.get("/api/audit/logs", response_model=List[AuditEntry])
async def get_audit_logs(limit: int = Query(default=100, ge=1, le=1000)):
    logs = await db.get_audit_logs(limit=limit)
    return [
        AuditEntry(
            id=row["id"],
            request_id=row["request_id"],
            timestamp=row["timestamp"],
            query_name=row["query_name"],
            is_flagged=bool(row["is_flagged"]),
            match_rule=row["match_rule"],
            highest_score=row["highest_score"],
            matched_entity_id=row["matched_entity_id"],
            matched_entity_name=row["matched_entity_name"]
        )
        for row in logs
    ]
