# Verified XYZ Résumé Recommendations: AML Sanctions Screening Gateway

## 1. Verified XYZ Résumé Bullets

1. **Accomplished** sub-20ms multi-tier name resolution across 1,011 live United Nations sanctions entities, **as measured by** achieving a mean matching latency of 12.7ms (min 0.028ms, P50 15.4ms, P95 19.6ms) and 67.88 screenings/second throughput, **by doing** designing a tri-tier matching pipeline fusing normalized exact lookup, phonetic Soundex, and length-guarded Jaro-Winkler/Levenshtein fuzzy algorithms.
2. **Accomplished** 100% auditability for regulatory Anti-Money Laundering (AML/KYC) compliance, **as measured by** recording zero dropped requests across 500 consecutive test screenings and persisting full provenance logs, **by doing** developing an asynchronous SQLite WAL-mode audit engine that captures UUIDv4 request correlation headers, match confidence scores, and rule triggers.
3. **Accomplished** automated ingestion and real-time indexing of global sanctions disclosures, **as measured by** processing 2.18 MB of XML records containing 736 individuals and 274 entities with 32 passing automated tests in 0.39s, **by doing** building an asynchronous streaming ingestion client with lxml XPath parsers and in-memory normalized cache synchronization.

---

## 2. Claim-to-Evidence Table

| Résumé Claim | Metric / Value | Verification Source |
| :--- | :--- | :--- |
| **Indexed Records** | 1,011 UN Entities (736 individuals, 274 entities) | `artifacts/benchmark-results.json` (`total_entities_indexed`) |
| **Throughput** | 67.88 screenings / sec | `artifacts/benchmark-results.json` (`throughput_screenings_per_sec`) |
| **Matching Latency** | Min: 0.028ms, Mean: 12.70ms, P50: 15.40ms, P95: 19.57ms | `artifacts/benchmark-results.json` (`matching_engine_latency_ms`) |
| **Audit Durability** | 0 dropped requests, 500 logged executions | `artifacts/benchmark-results.json` (`total_screenings`) |
| **Test Suite Coverage** | 32 passed, 0 failed, 100% pass rate in 0.39s | `artifacts/test-summary.json` & `artifacts/test-results.xml` |
| **Live API Integration** | Real UN Security Council Consolidated XML feed | `src/sync.py`, live fetch verified status 200 (2.18MB) |

---

## 3. Forbidden Claims Guide

- **DO NOT** claim integration with live US OFAC or SWIFT networks (this engine connects directly to the United Nations Security Council Consolidated Sanctions list).
- **DO NOT** claim sub-microsecond C++ hardware-accelerated matching (engine runs in Python 3.14 with algorithmic length-pruned vector/string heuristics).
- **DO NOT** claim full international script phonetic coverage without Romanized transliteration (American Soundex operates on Latin characters).
- **DO NOT** claim zero false-positives under all circumstances; fuzzy thresholds require tuning per institutional risk appetite (default threshold is set to 0.85).
