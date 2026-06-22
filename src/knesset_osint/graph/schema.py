"""Graph schema: uniqueness constraints + idempotent MERGE-based writers.

This module defines the *shape* of the corruption / conflict-of-interest graph
and the only sanctioned way to write to it. Everything here is:

  * **Idempotent** — every writer uses `MERGE` on a node's natural key, so
    re-projecting the same relational data never creates duplicates. This matters
    because the platform re-ingests sources on a schedule.
  * **Parameterized** — caller data is ALWAYS passed in the `parameters` dict and
    referenced as `$param` inside Cypher. We never f-string/`%`-format values into
    the query text. (Cypher injection is a real risk: an attacker-controlled
    company name must never be able to change query structure.)
  * **Provenance-aware** — writers accept the standard provenance fields
    (`source_type`, `source_url`, `fetched_at`) and stamp them onto nodes/edges,
    so every graph element can be traced back to an original document. Missing
    values are stored as NULL — we never fabricate a source.

GRAPH MODEL
-----------
Node labels and their natural (unique) keys:
  * (:Politician {knesset_person_id})   — the MK / official; mirrors models.Politician.
  * (:Person     {name})                — a non-MK individual (relative, business partner).
  * (:Company    {registration_id})     — a corporate entity (Corporations Authority id).
  * (:Tender     {tender_id})           — a public tender / contract.

Relationship types (direction matters; read them as English sentences):
  * (Politician)-[:RELATED_TO {relation}]->(Person)   "X is related to Y (spouse/sibling/...)"
  * (Person)-[:OWNS {role}]->(Company)                "Y owns/controls/directs company C"
      (use the `controls` flag / role string to distinguish OWNS vs CONTROLS semantics)
  * (Company)-[:AWARDED]->(Tender)                     "company C was awarded tender T"

The corruption SIGNAL is the traversable path, e.g.:
    (:Politician)-[:RELATED_TO]->(:Person)-[:OWNS]->(:Company)-[:AWARDED]->(:Tender)
The edges state sourced facts; a human analyst reads intent off the pattern. We
never label an edge "corrupt".

EXTENDING THE SCHEMA (the recipe)
---------------------------------
To add a new entity (say a :Donation node, or a :Trust node):
  1. Pick a stable natural key (an upstream id). Add a uniqueness constraint for it
     in `ensure_constraints` (this keeps MERGE idempotent and indexed).
  2. Add an `upsert_<thing>(...)` writer that MERGEs on that key and `SET`s the
     rest via `ON CREATE`/`ON MATCH` so updates are non-destructive.
  3. Add `link_<a>_<b>(...)` writers that MATCH both endpoints by their keys and
     MERGE the relationship, with edge properties in `$props`.
Keep every value in the parameters dict. Done.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from knesset_osint.core.logging import get_logger
from knesset_osint.graph.client import GraphClient

logger = get_logger("graph.schema")


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #
# One uniqueness constraint per node label, keyed on its natural id. Neo4j backs
# each uniqueness constraint with an index, so MERGE on these keys is O(log n),
# not a full scan. `IF NOT EXISTS` makes `ensure_constraints` safe to run on
# every startup. To add a label, append one line here (see EXTENDING above).
_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    # (constraint_name, node_label, key_property)
    ("politician_kns_id_unique", "Politician", "knesset_person_id"),
    ("person_name_unique", "Person", "name"),
    ("company_reg_id_unique", "Company", "registration_id"),
    ("tender_id_unique", "Tender", "tender_id"),
)


def ensure_constraints(client: GraphClient) -> list[str]:
    """Create all uniqueness constraints (idempotent).

    Returns the list of constraint names attempted. In no-op mode (graph
    disabled) nothing is sent and the names are still returned for logging/tests.
    Call this once at startup / before the first projection run.
    """
    created: list[str] = []
    for name, label, prop in _CONSTRAINTS:
        # Label and property here are developer-controlled literals from the table
        # above (NOT user input), so embedding them is safe. Any *value* a writer
        # stores still goes through $parameters.
        cypher = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        client.run(cypher)
        created.append(name)
    logger.info("ensure_constraints: %d constraints ensured", len(created))
    return created


# --------------------------------------------------------------------------- #
# Provenance helper
# --------------------------------------------------------------------------- #
def _provenance(
    source_type: Optional[str],
    source_url: Optional[str],
    fetched_at: Optional[datetime],
) -> dict[str, Any]:
    """Build the standard provenance parameter block.

    Mirrors `db.mixins.ProvenanceMixin`: every graph element carries where it came
    from. `source_type` is accepted as a plain string (pass `SourceType.x.value`)
    so this module stays decoupled from the SQL enum. Missing values stay NULL —
    we never invent a source.
    """
    return {
        "source_type": source_type,
        "source_url": source_url,
        # Store as ISO-8601 text: portable, and we don't take a hard dependency on
        # the server's temporal types for what is essentially audit metadata.
        "fetched_at": fetched_at.isoformat() if isinstance(fetched_at, datetime) else fetched_at,
    }


# --------------------------------------------------------------------------- #
# Node upserts (idempotent via MERGE on natural key)
# --------------------------------------------------------------------------- #
def upsert_politician(
    client: GraphClient,
    politician: Any,
    *,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """MERGE a (:Politician) node from a `models.Politician` (or a duck-typed obj).

    Keyed on `knesset_person_id` (the authoritative ParliamentInfo id). Non-key
    attributes are refreshed on every call so the graph tracks the relational
    source. Provenance defaults to the politician's own provenance fields when not
    supplied explicitly.

    Returns the created/matched node as a single-row list (empty in no-op mode).
    """
    kns_id = getattr(politician, "knesset_person_id", None)
    if kns_id is None:
        # Without the natural key we cannot MERGE idempotently. Refuse rather than
        # minting a duplicate or a fabricated id.
        logger.warning("upsert_politician skipped: politician has no knesset_person_id")
        return []

    prov = _provenance(
        source_type or getattr(getattr(politician, "source_type", None), "value", None) or _enum_value(politician, "source_type"),
        source_url or getattr(politician, "source_url", None),
        fetched_at or getattr(politician, "fetched_at", None),
    )
    params = {
        "kns_id": kns_id,
        "full_name": getattr(politician, "full_name", None),
        "first_name": getattr(politician, "first_name", None),
        "last_name": getattr(politician, "last_name", None),
        "is_current": getattr(politician, "is_current", None),
        "current_party": getattr(politician, "current_party", None),
        **prov,
    }
    cypher = """
    MERGE (p:Politician {knesset_person_id: $kns_id})
    SET p.full_name     = $full_name,
        p.first_name    = $first_name,
        p.last_name     = $last_name,
        p.is_current    = $is_current,
        p.current_party = $current_party,
        p.source_type   = $source_type,
        p.source_url    = $source_url,
        p.fetched_at    = $fetched_at
    RETURN p
    """
    return client.execute_write(cypher, params)


def upsert_person(
    client: GraphClient,
    name: str,
    role: Optional[str] = None,
    *,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """MERGE a (:Person) node — a non-MK individual (relative, partner, director).

    Keyed on `name`. Names are weak keys (homonyms exist); when you have a stronger
    identifier (national id hash, registry person id) add it as the key and a
    constraint per the EXTENDING recipe. `role` is a free-text descriptor of how
    this person appears in the source (e.g. "brother", "business partner").
    """
    prov = _provenance(source_type, source_url, fetched_at)
    params = {"name": name, "role": role, **prov}
    cypher = """
    MERGE (x:Person {name: $name})
    SET x.role        = coalesce($role, x.role),
        x.source_type = $source_type,
        x.source_url  = $source_url,
        x.fetched_at  = $fetched_at
    RETURN x
    """
    return client.execute_write(cypher, params)


def upsert_company(
    client: GraphClient,
    name: Optional[str],
    registration_id: str,
    *,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """MERGE a (:Company) node, keyed on the Corporations Authority `registration_id`.

    `registration_id` is the stable key; `name` is a refreshed attribute (companies
    rename). Pass the registry id you ingested — never synthesise one.
    """
    prov = _provenance(source_type, source_url, fetched_at)
    params = {"reg_id": registration_id, "name": name, **prov}
    cypher = """
    MERGE (c:Company {registration_id: $reg_id})
    SET c.name        = coalesce($name, c.name),
        c.source_type = $source_type,
        c.source_url  = $source_url,
        c.fetched_at  = $fetched_at
    RETURN c
    """
    return client.execute_write(cypher, params)


def upsert_tender(
    client: GraphClient,
    tender_id: str,
    title: Optional[str] = None,
    *,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """MERGE a (:Tender) node, keyed on the publishing body's `tender_id`.

    Represents a public tender / awarded contract. `title` is a refreshed
    attribute. Combine with `link_tender_award` to record who won it.
    """
    prov = _provenance(source_type, source_url, fetched_at)
    params = {"tender_id": tender_id, "title": title, **prov}
    cypher = """
    MERGE (t:Tender {tender_id: $tender_id})
    SET t.title       = coalesce($title, t.title),
        t.source_type = $source_type,
        t.source_url  = $source_url,
        t.fetched_at  = $fetched_at
    RETURN t
    """
    return client.execute_write(cypher, params)


# --------------------------------------------------------------------------- #
# Relationship writers (MATCH endpoints by key, MERGE the edge)
# --------------------------------------------------------------------------- #
# Each linker MERGEs the (:Person)/(:Company)/(:Tender) endpoints by their natural
# keys first, so a link call also lazily creates any missing nodes — handy when a
# relative or partner is only ever seen via an edge. Edge metadata travels in a
# single `$props`-style set of parameters; the `relation`/`role` strings describe
# the source-stated nature of the tie. We never collapse distinct sources into one
# edge silently — re-runs just refresh the edge's provenance.

def link_relative(
    client: GraphClient,
    politician_node: Any,
    relative_name: str,
    relation: str,
    *,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Create (:Politician)-[:RELATED_TO {relation}]->(:Person).

    `politician_node` may be a `models.Politician`, a dict, or a raw int — anything
    we can resolve a `knesset_person_id` from (so callers can pass the ORM object
    they already have). `relation` is the source-stated kinship/association
    (e.g. "spouse", "son", "cousin"). The edge stores the relation + provenance;
    it does NOT imply impropriety.
    """
    kns_id = _resolve_kns_id(politician_node)
    if kns_id is None:
        logger.warning("link_relative skipped: could not resolve knesset_person_id")
        return []

    prov = _provenance(source_type, source_url, fetched_at)
    params = {"kns_id": kns_id, "name": relative_name, "relation": relation, **prov}
    # MERGE the person too, so a relative seen only here still gets a node.
    cypher = """
    MERGE (p:Politician {knesset_person_id: $kns_id})
    MERGE (r:Person {name: $name})
    MERGE (p)-[rel:RELATED_TO {relation: $relation}]->(r)
    SET rel.source_type = $source_type,
        rel.source_url  = $source_url,
        rel.fetched_at  = $fetched_at
    RETURN p, rel, r
    """
    return client.execute_write(cypher, params)


def link_ownership(
    client: GraphClient,
    person: str,
    company: str,
    role: Optional[str] = None,
    *,
    controls: bool = False,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Create (:Person)-[:OWNS|:CONTROLS {role}]->(:Company).

    `person` is the person's name (natural key of :Person); `company` is the
    company's `registration_id` (natural key of :Company). Set `controls=True` to
    record control without legal ownership (director/beneficial controller); this
    selects the :CONTROLS relationship type instead of :OWNS. `role` is the
    source-stated capacity (e.g. "shareholder", "director", "beneficial owner").

    Both endpoints are MERGEd so a link can precede a full node upsert.
    """
    # Relationship *type* cannot be parameterized in Cypher, so we choose between
    # two fixed, developer-controlled literals based on the `controls` flag. The
    # `role` value (which may be source-derived) is still passed as a parameter.
    rel_type = "CONTROLS" if controls else "OWNS"
    prov = _provenance(source_type, source_url, fetched_at)
    params = {"person": person, "company": company, "role": role, **prov}
    cypher = f"""
    MERGE (x:Person {{name: $person}})
    MERGE (c:Company {{registration_id: $company}})
    MERGE (x)-[o:{rel_type}]->(c)
    SET o.role        = coalesce($role, o.role),
        o.source_type = $source_type,
        o.source_url  = $source_url,
        o.fetched_at  = $fetched_at
    RETURN x, o, c
    """
    return client.execute_write(cypher, params)


def link_tender_award(
    client: GraphClient,
    company: str,
    tender: str,
    *,
    title: Optional[str] = None,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Create (:Company)-[:AWARDED]->(:Tender).

    `company` is the company `registration_id`; `tender` is the `tender_id`.
    Optionally pass `title` to enrich the tender node in the same write. The edge
    records that the company won the tender, with a link back to the source.
    """
    prov = _provenance(source_type, source_url, fetched_at)
    params = {"company": company, "tender": tender, "title": title, **prov}
    cypher = """
    MERGE (c:Company {registration_id: $company})
    MERGE (t:Tender {tender_id: $tender})
    SET t.title = coalesce($title, t.title)
    MERGE (c)-[a:AWARDED]->(t)
    SET a.source_type = $source_type,
        a.source_url  = $source_url,
        a.fetched_at  = $fetched_at
    RETURN c, a, t
    """
    return client.execute_write(cypher, params)


# --------------------------------------------------------------------------- #
# Small internal resolvers (kept private to this module)
# --------------------------------------------------------------------------- #
def _resolve_kns_id(politician_node: Any) -> Optional[int]:
    """Best-effort extraction of a knesset_person_id from varied caller inputs.

    Accepts: an int, a `models.Politician`-like object, or a dict. Returns None if
    nothing usable is found — callers must handle the skip rather than guessing.
    """
    if isinstance(politician_node, int):
        return politician_node
    if isinstance(politician_node, dict):
        return politician_node.get("knesset_person_id")
    return getattr(politician_node, "knesset_person_id", None)


def _enum_value(obj: Any, attr: str) -> Optional[str]:
    """Return the `.value` of an enum-typed attribute, or the raw value, or None.

    Lets `upsert_politician` accept either an ORM object whose `source_type` is a
    `SourceType` enum or a plain string, without importing the enum here.
    """
    val = getattr(obj, attr, None)
    if val is None:
        return None
    return getattr(val, "value", val)
