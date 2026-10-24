from typing import Optional, List
from pydantic import BaseModel, Field


class SanctionedEntity(BaseModel):
    id: str
    entity_type: str = Field(..., description="INDIVIDUAL or ENTITY")
    primary_name: str
    aliases: List[str] = Field(default_factory=list)
    un_reference_num: str
    nationality: Optional[str] = None
    listed_on: Optional[str] = None
    remarks: Optional[str] = None


class MatchDetail(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    score: float
    matched_alias: Optional[str] = None
    match_tier: str
    rule: str


class ScreeningRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Entity or individual name to screen")
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    entity_type: Optional[str] = Field(default=None, description="Optional filter: INDIVIDUAL or ENTITY")


class ScreeningResult(BaseModel):
    query_name: str
    is_flagged: bool
    total_matches: int
    highest_score: float
    matches: List[MatchDetail] = Field(default_factory=list)
    screened_at: str
    execution_time_ms: float


class BatchScreeningRequest(BaseModel):
    names: List[str] = Field(..., min_length=1, description="List of names to screen")
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class BatchScreeningResult(BaseModel):
    total_screened: int
    total_flagged: int
    results: List[ScreeningResult]
    execution_time_ms: float


class AuditEntry(BaseModel):
    id: int
    request_id: str
    timestamp: str
    query_name: str
    is_flagged: bool
    match_rule: str
    highest_score: float
    matched_entity_id: Optional[str] = None
    matched_entity_name: Optional[str] = None


class SyncResponse(BaseModel):
    status: str
    total_individuals: int
    total_entities: int
    synced_at: str
    duration_seconds: float


class HealthResponse(BaseModel):
    status: str
    database_status: str
    total_entities_indexed: int
    last_sync_timestamp: Optional[str] = None
