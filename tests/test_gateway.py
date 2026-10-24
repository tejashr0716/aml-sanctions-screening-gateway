import os
import pytest
from httpx import AsyncClient, ASGITransport
from src.matcher import (
    normalize_string,
    compute_soundex_token,
    compute_soundex,
    levenshtein_distance,
    levenshtein_similarity,
    jaro_similarity,
    jaro_winkler_similarity,
    MultiTierMatcher
)
from src.models import (
    ScreeningRequest,
    BatchScreeningRequest
)
from src.database import db
from src.sync import SanctionsSyncService
from src.screener import screener
from src.main import app


# -------------------------------------------------------------
# 1. Normalization Tests
# -------------------------------------------------------------
def test_normalize_accents_and_case():
    assert normalize_string("Éric") == "eric"
    assert normalize_string("MÜLLER") == "muller"
    assert normalize_string("François") == "francois"


def test_normalize_punctuation_and_whitespace():
    assert normalize_string("Al-Qaida / Al-Qaeda") == "al qaida al qaeda"
    assert normalize_string("   John    Smith   ") == "john smith"
    assert normalize_string("") == ""
    assert normalize_string(None) == ""


def test_normalize_special_characters():
    assert normalize_string("O'Connor & Sons #1") == "o connor sons 1"


# -------------------------------------------------------------
# 2. Soundex Tests
# -------------------------------------------------------------
def test_soundex_single_tokens():
    assert compute_soundex_token("Robert") == "R163"
    assert compute_soundex_token("Rupert") == "R163"
    assert compute_soundex_token("Ashcraft") == "A261"


def test_soundex_empty_and_special():
    assert compute_soundex_token("") == "0000"
    assert compute_soundex_token("123") == "0000"


def test_soundex_multi_token():
    assert compute_soundex("Vladimir Putin") == "V435 P350"
    assert compute_soundex("   ") == "0000"


# -------------------------------------------------------------
# 3. Levenshtein Distance & Similarity Tests
# -------------------------------------------------------------
def test_levenshtein_identical():
    assert levenshtein_distance("test", "test") == 0
    assert levenshtein_similarity("test", "test") == 1.0


def test_levenshtein_empty():
    assert levenshtein_distance("", "test") == 4
    assert levenshtein_distance("test", "") == 4
    assert levenshtein_similarity("", "test") == 0.0


def test_levenshtein_variations():
    assert levenshtein_distance("kitten", "sitting") == 3
    sim = levenshtein_similarity("kitten", "sitting")
    assert 0.5 < sim < 0.6


# -------------------------------------------------------------
# 4. Jaro & Jaro-Winkler Similarity Tests
# -------------------------------------------------------------
def test_jaro_identical():
    assert jaro_similarity("martha", "martha") == 1.0
    assert jaro_winkler_similarity("martha", "martha") == 1.0


def test_jaro_empty():
    assert jaro_similarity("", "martha") == 0.0
    assert jaro_similarity("martha", "") == 0.0


def test_jaro_winkler_prefix_bonus():
    jaro = jaro_similarity("martha", "marhta")
    jw = jaro_winkler_similarity("martha", "marhta")
    assert jw >= jaro
    assert jw > 0.90


# -------------------------------------------------------------
# 5. Multi-Tier Matcher Tests
# -------------------------------------------------------------
def test_matcher_tier1_exact():
    matcher = MultiTierMatcher(default_threshold=0.85)
    matched, score, tier, rule = matcher.evaluate_pair("Eric Badege", "eric  badege")
    assert matched is True
    assert score == 1.0
    assert tier == "TIER_1_EXACT"
    assert rule == "EXACT_NORMALIZED"


def test_matcher_tier1_token_permutation():
    matcher = MultiTierMatcher(default_threshold=0.85)
    matched, score, tier, rule = matcher.evaluate_pair("Badege Eric", "Eric Badege")
    assert matched is True
    assert score >= 0.98
    assert tier == "TIER_1_EXACT"
    assert rule == "EXACT_TOKEN_PERMUTATION"


def test_matcher_tier2_phonetic():
    matcher = MultiTierMatcher(default_threshold=0.85)
    # Robert vs Rupert share soundex R163
    matched, score, tier, rule = matcher.evaluate_pair("Robert", "Rupert")
    assert matched is True
    assert tier == "TIER_2_PHONETIC"
    assert rule == "PHONETIC_SOUNDEX"


def test_matcher_tier3_fuzzy():
    matcher = MultiTierMatcher(default_threshold=0.85)
    # Wladimir and Vladimir have different Soundex (W435 vs V435) but high fuzzy similarity
    matched, score, tier, rule = matcher.evaluate_pair("Wladimir Putin", "Vladimir Putin")
    assert matched is True
    assert tier == "TIER_3_FUZZY"
    assert score >= 0.85


def test_matcher_below_threshold():
    matcher = MultiTierMatcher(default_threshold=0.85)
    matched, score, tier, rule = matcher.evaluate_pair("John Doe", "Alexander Smith")
    assert matched is False
    assert tier == "NONE"
    assert rule == "BELOW_THRESHOLD"


# -------------------------------------------------------------
# 6. XML Parsing Tests
# -------------------------------------------------------------
def test_parse_sample_xml():
    sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <CONSOLIDATED_LIST>
        <INDIVIDUALS>
            <INDIVIDUAL>
                <DATAID>9991</DATAID>
                <FIRST_NAME>Test</FIRST_NAME>
                <SECOND_NAME>Individual</SECOND_NAME>
                <REFERENCE_NUMBER>TEST-001</REFERENCE_NUMBER>
                <LISTED_ON>2024-01-01</LISTED_ON>
                <COMMENTS1>Test individual comments</COMMENTS1>
                <INDIVIDUAL_ALIAS>
                    <ALIAS_NAME>Test Alias 1</ALIAS_NAME>
                </INDIVIDUAL_ALIAS>
                <NATIONALITY><VALUE>Testland</VALUE></NATIONALITY>
            </INDIVIDUAL>
        </INDIVIDUALS>
        <ENTITIES>
            <ENTITY>
                <DATAID>9992</DATAID>
                <FIRST_NAME>Test Entity Ltd</FIRST_NAME>
                <REFERENCE_NUMBER>TEST-002</REFERENCE_NUMBER>
                <LISTED_ON>2024-02-01</LISTED_ON>
                <COMMENTS1>Test entity comments</COMMENTS1>
                <ENTITY_ALIAS>
                    <ALIAS_NAME>TEL Corp</ALIAS_NAME>
                </ENTITY_ALIAS>
            </ENTITY>
        </ENTITIES>
    </CONSOLIDATED_LIST>
    """
    svc = SanctionsSyncService()
    entities = svc.parse_xml_to_entities(sample_xml)
    assert len(entities) == 2
    assert entities[0]["id"] == "UN-IND-9991"
    assert entities[0]["primary_name"] == "Test Individual"
    assert "Test Alias 1" in entities[0]["aliases"]
    assert entities[1]["id"] == "UN-ENT-9992"
    assert entities[1]["primary_name"] == "Test Entity Ltd"
    assert "TEL Corp" in entities[1]["aliases"]


# -------------------------------------------------------------
# 7. Database & Screener Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_database_insert_and_count():
    db.init_sync_db()
    test_data = [{
        "id": "MOCK-1",
        "entity_type": "INDIVIDUAL",
        "primary_name": "Marcus Aurelius Test",
        "aliases": ["The Philosopher", "Emperor Marcus"],
        "un_reference_num": "UN-MOCK-1",
        "nationality": "Roman",
        "listed_on": "2024-01-01",
        "remarks": "Mock record for unit testing"
    }]
    await db.insert_entities_batch(test_data, clear_existing=False)
    await screener.reload_cache()
    count = await db.get_total_entities_count()
    assert count > 0


@pytest.mark.asyncio
async def test_screener_exact_hit():
    req = ScreeningRequest(name="Marcus Aurelius Test")
    result = await screener.screen_entity(req)
    assert result.is_flagged is True
    assert result.total_matches >= 1
    assert result.matches[0].score == 1.0
    assert result.matches[0].entity_id == "MOCK-1"


@pytest.mark.asyncio
async def test_screener_alias_hit():
    req = ScreeningRequest(name="Emperor Marcus")
    result = await screener.screen_entity(req)
    assert result.is_flagged is True
    assert result.total_matches >= 1
    assert result.matches[0].entity_id == "MOCK-1"
    assert result.matches[0].matched_alias == "Emperor Marcus"


@pytest.mark.asyncio
async def test_screener_clean_query():
    req = ScreeningRequest(name="Arthur Pendelton 99")
    result = await screener.screen_entity(req)
    assert result.is_flagged is False
    assert result.total_matches == 0
    assert result.highest_score < 0.85


@pytest.mark.asyncio
async def test_screener_entity_type_filter():
    req_ent = ScreeningRequest(name="Marcus Aurelius Test", entity_type="ENTITY")
    result = await screener.screen_entity(req_ent)
    # Since Marcus is an INDIVIDUAL, filtering for ENTITY yields no matches
    assert result.is_flagged is False


@pytest.mark.asyncio
async def test_screener_batch_evaluation():
    batch = BatchScreeningRequest(
        names=["Marcus Aurelius Test", "Arthur Pendelton 99", "The Philosopher"]
    )
    res = await screener.screen_batch(batch)
    assert res.total_screened == 3
    assert res.total_flagged == 2
    assert len(res.results) == 3


@pytest.mark.asyncio
async def test_audit_logs_recorded_and_immutable():
    logs = await db.get_audit_logs(limit=10)
    assert len(logs) > 0
    first = logs[0]
    assert "request_id" in first
    assert "timestamp" in first
    assert "query_name" in first
    assert "is_flagged" in first


# -------------------------------------------------------------
# 8. API Endpoints & Contract Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "HEALTHY"
        assert data["database_status"] == "CONNECTED"
        assert "total_entities_indexed" in data


@pytest.mark.asyncio
async def test_api_screen_entity_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"name": "Marcus Aurelius Test", "threshold": 0.85}
        resp = await ac.post("/api/screen/entity", json=payload, headers={"X-Request-ID": "custom-uuid-101"})
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == "custom-uuid-101"
        data = resp.json()
        assert data["is_flagged"] is True
        assert data["query_name"] == "Marcus Aurelius Test"


@pytest.mark.asyncio
async def test_api_screen_batch_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"names": ["Marcus Aurelius Test", "Clean Person ABC"]}
        resp = await ac.post("/api/screen/batch", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_screened"] == 2
        assert data["total_flagged"] >= 1


@pytest.mark.asyncio
async def test_api_audit_logs_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/audit/logs?limit=5")
        assert resp.status_code == 200
        logs = resp.json()
        assert isinstance(logs, list)
        assert len(logs) <= 5


@pytest.mark.asyncio
async def test_api_validation_error_on_empty_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/screen/entity", json={"name": ""})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_api_validation_error_on_invalid_threshold():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/screen/entity", json={"name": "Test", "threshold": 1.5})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_live_un_sanctions_data_check():
    """Verify live UN sanctions entries are present and queryable."""
    req = ScreeningRequest(name="ERIC BADEGE")
    res = await screener.screen_entity(req)
    assert res.is_flagged is True
    assert res.highest_score == 1.0
