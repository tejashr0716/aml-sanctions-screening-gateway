import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import httpx
from lxml import etree
from src.config import settings
from src.database import db

logger = logging.getLogger(__name__)


class SanctionsSyncService:
    """Synchronizes UN Consolidated Sanctions XML into local SQLite database."""

    def __init__(self, feed_url: Optional[str] = None):
        self.feed_url = feed_url or settings.SANCTIONS_FEED_URL

    async def fetch_xml_content(self) -> bytes:
        """Fetch live XML feed from United Nations endpoint."""
        headers = {
            "User-Agent": "AMLSanctionsGateway/1.0 (compliance@enterprise-risk.internal)",
            "Accept": "application/xml, text/xml, */*"
        }
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = await client.get(self.feed_url, headers=headers)
            resp.raise_for_status()
            return resp.content

    def parse_xml_to_entities(self, xml_bytes: bytes) -> List[Dict[str, Any]]:
        """Parse UN Consolidated XML into normalized dictionary list."""
        root = etree.fromstring(xml_bytes)
        entities: List[Dict[str, Any]] = []

        # Parse INDIVIDUALS
        for ind in root.xpath("//INDIVIDUAL"):
            data_id_elem = ind.find("DATAID")
            data_id = data_id_elem.text.strip() if data_id_elem is not None and data_id_elem.text else None
            if not data_id:
                continue

            name_parts = []
            for tag in ["FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME"]:
                elem = ind.find(tag)
                if elem is not None and elem.text and elem.text.strip():
                    name_parts.append(elem.text.strip())
            
            primary_name = " ".join(name_parts) if name_parts else f"UNKNOWN_INDIVIDUAL_{data_id}"

            ref_elem = ind.find("REFERENCE_NUMBER")
            ref_num = ref_elem.text.strip() if ref_elem is not None and ref_elem.text else ""

            listed_elem = ind.find("LISTED_ON")
            listed_on = listed_elem.text.strip() if listed_elem is not None and listed_elem.text else ""

            comments_elem = ind.find("COMMENTS1")
            remarks = comments_elem.text.strip() if comments_elem is not None and comments_elem.text else ""

            nat_elem = ind.xpath(".//NATIONALITY/VALUE")
            nationality = nat_elem[0].text.strip() if nat_elem and nat_elem[0].text else ""

            aliases = []
            for alias_elem in ind.xpath(".//INDIVIDUAL_ALIAS/ALIAS_NAME"):
                if alias_elem.text and alias_elem.text.strip():
                    aliases.append(alias_elem.text.strip())

            entities.append({
                "id": f"UN-IND-{data_id}",
                "entity_type": "INDIVIDUAL",
                "primary_name": primary_name,
                "aliases": aliases,
                "un_reference_num": ref_num,
                "nationality": nationality,
                "listed_on": listed_on,
                "remarks": remarks
            })

        # Parse ENTITIES
        for ent in root.xpath("//ENTITY"):
            data_id_elem = ent.find("DATAID")
            data_id = data_id_elem.text.strip() if data_id_elem is not None and data_id_elem.text else None
            if not data_id:
                continue

            first_name_elem = ent.find("FIRST_NAME")
            primary_name = first_name_elem.text.strip() if first_name_elem is not None and first_name_elem.text else f"UNKNOWN_ENTITY_{data_id}"

            ref_elem = ent.find("REFERENCE_NUMBER")
            ref_num = ref_elem.text.strip() if ref_elem is not None and ref_elem.text else ""

            listed_elem = ent.find("LISTED_ON")
            listed_on = listed_elem.text.strip() if listed_elem is not None and listed_elem.text else ""

            comments_elem = ent.find("COMMENTS1")
            remarks = comments_elem.text.strip() if comments_elem is not None and comments_elem.text else ""

            aliases = []
            for alias_elem in ent.xpath(".//ENTITY_ALIAS/ALIAS_NAME"):
                if alias_elem.text and alias_elem.text.strip():
                    aliases.append(alias_elem.text.strip())

            entities.append({
                "id": f"UN-ENT-{data_id}",
                "entity_type": "ENTITY",
                "primary_name": primary_name,
                "aliases": aliases,
                "un_reference_num": ref_num,
                "nationality": "",
                "listed_on": listed_on,
                "remarks": remarks
            })

        return entities

    async def sync_now(self) -> Dict[str, Any]:
        """Perform full sync from live UN endpoint into database."""
        start_time = time.perf_counter()
        xml_content = await self.fetch_xml_content()
        entities = self.parse_xml_to_entities(xml_content)

        ind_count = sum(1 for e in entities if e["entity_type"] == "INDIVIDUAL")
        ent_count = sum(1 for e in entities if e["entity_type"] == "ENTITY")

        await db.insert_entities_batch(entities, clear_existing=True)
        await db.record_sync_metadata(ind_count, ent_count, self.feed_url)

        duration = time.perf_counter() - start_time
        return {
            "status": "SUCCESS",
            "total_individuals": ind_count,
            "total_entities": ent_count,
            "total_records": len(entities),
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 4)
        }


sync_service = SanctionsSyncService()
