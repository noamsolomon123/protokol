"""Central configuration.

All tunables and source endpoints live here so that scaling to new politicians
or new data sources is a config/adapter change, never a code-spelunking exercise.

Values are read from environment variables (see `.env.example`); every field has
a safe local-dev default. Endpoint defaults were verified against the live APIs
on 2026-06-20.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Knesset OSINT Platform"
    environment: str = "development"
    log_level: str = "INFO"

    # --- PostgreSQL (structured data) ---
    database_url: str = "postgresql+psycopg2://osint:osint@localhost:5432/osint"

    # --- Neo4j (entity / corruption graph) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change_me_neo4j"
    neo4j_enabled: bool = True

    # --- HTTP / ingestion tuning ---
    http_user_agent: str = "knesset-osint/0.1 (civic transparency research)"
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 4
    odata_page_size: int = 100

    # --- Source base URLs (verified live 2026-06-20) ---
    # ParliamentInfo OData V4: persons, bills, bill-initiators, positions.
    knesset_odata_v4_base: str = "https://knesset.gov.il/OdataV4/ParliamentInfo"
    # Votes OData V3 (.svc): the V4 Votes service is bot-protected (Imperva);
    # the V3 .svc is the clean, open official path. DO NOT add evasion logic.
    knesset_votes_svc_base: str = "https://knesset.gov.il/Odata/Votes.svc"
    # Open Knesset (Hasadna) — enrichment / fallback only, never source-of-truth.
    open_knesset_pipelines_base: str = "https://production.oknesset.org/pipelines/data"
    knesset_data_gcs_base: str = "https://storage.googleapis.com/knesset-data-pipelines/data"

    # --- Pilot scope ---
    # Benjamin Netanyahu — KNS_Person.Id, verified live (LastName=נתניהו, IsCurrent=true).
    pilot_person_id: int = 965
    pilot_party_he: str = "הליכוד"
    pilot_party_en: str = "Likud"
    enable_open_knesset_enrichment: bool = True


@lru_cache
def get_settings() -> Settings:
    """Cached singleton accessor. Use this everywhere instead of `Settings()`."""
    return Settings()


settings = get_settings()
