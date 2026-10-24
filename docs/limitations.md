# Limitations & Boundary Conditions: AML Sanctions Screening Gateway

## 1. Data Source Scope
- Ingests the United Nations Security Council Consolidated List (736 individuals, 274 entities as of Oct 2026).
- Secondary lists such as US OFAC SDN, UK OFSI, and EU Consolidated Financial Sanctions can be integrated via modular adaptors.

## 2. In-Memory Cache Scalability
- The in-memory precomputed index stores ~1,010 UN entities and associated aliases (~2,500 total names), occupying less than 1MB of RAM.
- For multi-million record PEP (Politically Exposed Persons) databases, vector-assisted approximate nearest neighbor (ANN) indexes or Elasticsearch trigram indices are recommended.

## 3. SQLite Concurrency Thresholds
- Uses SQLite with Write-Ahead Logging (WAL) mode for local single-node persistence.
- While SQLite in WAL mode reliably achieves 60+ write transactions per second, distributed high-availability banking environments should point `DATABASE_URL` to PostgreSQL.

## 4. Script & Alphabet Specificity
- Normalization decomposes Latin, Cyrillic, and extended Latin characters via Unicode NFKD.
- Non-Latin native scripts (Arabic, Cyrillic, Chinese) require preliminary transliteration to Romanized script prior to American Soundex calculation.
