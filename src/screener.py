import time
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import aiosqlite
from src.config import settings
from src.database import db
from src.models import (
    ScreeningRequest,
    ScreeningResult,
    MatchDetail,
    BatchScreeningRequest,
    BatchScreeningResult
)
from src.matcher import (
    MultiTierMatcher,
    normalize_string,
    compute_soundex
)


class SanctionsScreener:
    """High-performance multi-tier sanctions screener with in-memory caching and persistent audit logging."""

    def __init__(self):
        self.matcher = MultiTierMatcher(default_threshold=settings.FUZZY_MATCH_THRESHOLD)
        self._cache: List[Dict[str, Any]] = []
        self._exact_primary_map: Dict[str, Dict[str, Any]] = {}
        self._cache_loaded = False

    async def reload_cache(self):
        """Reload indexed entities into memory with precomputed normalizations."""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id, entity_type, primary_name, primary_name_norm, aliases, soundex FROM entities;"
            )
            rows = await cursor.fetchall()
            cached = []
            exact_map = {}
            for r in rows:
                aliases_raw = r["aliases"]
                aliases = json.loads(aliases_raw) if aliases_raw else []
                aliases_data = [
                    (alias, normalize_string(alias), compute_soundex(alias))
                    for alias in aliases
                ]
                norm_p = r["primary_name_norm"] or normalize_string(r["primary_name"])
                soundex_p = r["soundex"] or compute_soundex(r["primary_name"])
                item = {
                    "id": r["id"],
                    "entity_type": r["entity_type"],
                    "primary_name": r["primary_name"],
                    "primary_name_norm": norm_p,
                    "soundex": soundex_p,
                    "aliases_data": aliases_data
                }
                cached.append(item)
                exact_map[norm_p] = item

            self._cache = cached
            self._exact_primary_map = exact_map
            self._cache_loaded = True

    async def ensure_cache(self):
        if not self._cache_loaded:
            await self.reload_cache()

    async def screen_entity(
        self,
        request: ScreeningRequest,
        request_id: str = "internal",
        write_audit_log: bool = True
    ) -> ScreeningResult:
        """Screen a single entity or individual against sanctions lists."""
        start_time = time.perf_counter()
        await self.ensure_cache()

        threshold = request.threshold if request.threshold is not None else settings.FUZZY_MATCH_THRESHOLD
        query_norm = normalize_string(request.name)
        query_soundex = compute_soundex(request.name)

        matches: List[MatchDetail] = []

        # Fast-path Tier 1 exact match
        if query_norm in self._exact_primary_map:
            item = self._exact_primary_map[query_norm]
            if not request.entity_type or item["entity_type"].upper() == request.entity_type.upper():
                matches.append(MatchDetail(
                    entity_id=item["id"],
                    entity_name=item["primary_name"],
                    entity_type=item["entity_type"],
                    score=1.0,
                    matched_alias=None,
                    match_tier="TIER_1_EXACT",
                    rule="EXACT_NORMALIZED"
                ))

        if not matches:
            for item in self._cache:
                if request.entity_type and item["entity_type"].upper() != request.entity_type.upper():
                    continue

                # 1. Test against primary name
                is_match, score, tier, rule = self.matcher.evaluate_normalized(
                    query_norm,
                    item["primary_name_norm"],
                    soundex_query=query_soundex,
                    soundex_cand=item["soundex"],
                    threshold=threshold
                )
                if is_match:
                    matches.append(MatchDetail(
                        entity_id=item["id"],
                        entity_name=item["primary_name"],
                        entity_type=item["entity_type"],
                        score=score,
                        matched_alias=None,
                        match_tier=tier,
                        rule=rule
                    ))
                    continue

                # 2. Test against aliases
                for alias_raw, alias_norm, alias_soundex in item["aliases_data"]:
                    is_a_match, a_score, a_tier, a_rule = self.matcher.evaluate_normalized(
                        query_norm,
                        alias_norm,
                        soundex_query=query_soundex,
                        soundex_cand=alias_soundex,
                        threshold=threshold
                    )
                    if is_a_match:
                        matches.append(MatchDetail(
                            entity_id=item["id"],
                            entity_name=item["primary_name"],
                            entity_type=item["entity_type"],
                            score=a_score,
                            matched_alias=alias_raw,
                            match_tier=a_tier,
                            rule=a_rule
                        ))
                        break

        matches.sort(key=lambda m: m.score, reverse=True)

        is_flagged = len(matches) > 0
        highest_score = matches[0].score if matches else 0.0
        top_rule = matches[0].rule if matches else "NO_MATCH"
        top_id = matches[0].entity_id if matches else None
        top_name = matches[0].entity_name if matches else None

        # Capture matching engine execution latency before I/O
        match_exec_ms = round((time.perf_counter() - start_time) * 1000, 3)

        if write_audit_log:
            await db.record_audit_log(
                request_id=request_id,
                query_name=request.name,
                is_flagged=is_flagged,
                match_rule=top_rule,
                highest_score=highest_score,
                matched_entity_id=top_id,
                matched_entity_name=top_name
            )

        return ScreeningResult(
            query_name=request.name,
            is_flagged=is_flagged,
            total_matches=len(matches),
            highest_score=highest_score,
            matches=matches,
            screened_at=datetime.now(timezone.utc).isoformat(),
            execution_time_ms=match_exec_ms
        )

    async def screen_batch(
        self,
        batch_request: BatchScreeningRequest,
        request_id: str = "internal-batch"
    ) -> BatchScreeningResult:
        """Screen a batch of names."""
        start_time = time.perf_counter()
        results: List[ScreeningResult] = []

        for name in batch_request.names:
            req = ScreeningRequest(name=name, threshold=batch_request.threshold)
            res = await self.screen_entity(req, request_id=request_id)
            results.append(res)

        total_flagged = sum(1 for r in results if r.is_flagged)
        exec_time_ms = round((time.perf_counter() - start_time) * 1000, 3)

        return BatchScreeningResult(
            total_screened=len(results),
            total_flagged=total_flagged,
            results=results,
            execution_time_ms=exec_time_ms
        )


screener = SanctionsScreener()
