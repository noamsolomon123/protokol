"""Neo4j graph layer — the corruption / conflict-of-interest map.

This package projects the authoritative relational data (PostgreSQL, owned by the
ingestion + models backbone) onto a property graph so analysts can traverse
*relationships between entities*: which politician is related to whom, who owns or
controls which company, and which company was awarded which public tender.

Design stance (matches the platform's objectivity invariants):
  * The graph is a **derived projection**, never a source of truth. Every node and
    edge should ultimately trace back to a provenanced relational row. Writers here
    accept the provenance fields (source_url, source_type, fetched_at) and stamp
    them onto nodes/edges so a click in the UI leads back to the original document.
  * Writers NEVER assert wrongdoing. An OWNS or AWARDED edge is a *fact with a
    source*; the corruption signal is the *pattern* a human reads off the graph
    (e.g. RELATED_TO a person who OWNS a company that was AWARDED a tender). The
    edges state facts; they do not state intent.
  * Neo4j is optional. When `settings.neo4j_enabled` is False every write is a
    safe no-op, so the rest of the platform runs without a graph database.

Public surface:
  * `GraphClient`     — connection wrapper (driver lifecycle, sessions, no-op mode).
  * `schema`          — `ensure_constraints` + idempotent MERGE-based writers.

Extending the graph (read this before adding entities):
  Adding a new node label or relationship type is a two-step change:
    1. Add a uniqueness constraint for the new label's natural key in
       `schema.ensure_constraints` (so MERGE stays idempotent and fast).
    2. Add an `upsert_<thing>` / `link_<a>_<b>` helper in `schema.py` that uses a
       parameterized MERGE. Keep all values in the `parameters` dict — never
       string-format caller data into Cypher.
  See module docstrings in `client.py` and `schema.py` for worked examples.
"""

from __future__ import annotations

from knesset_osint.graph.client import GraphClient

__all__ = ["GraphClient"]
