"""`GraphClient` — a thin lifecycle wrapper around the official Neo4j driver.

Responsibilities (deliberately small):
  * Own a single `neo4j.GraphDatabase.driver` built from `settings`
    (uri + basic auth). The driver is a connection pool and is thread-safe, so a
    long-lived `GraphClient` can be shared across the app.
  * Honour `settings.neo4j_enabled`: when False, the client never opens a socket
    and every operation becomes a logged no-op. This keeps the platform usable
    in environments without a graph DB (CI, local dev, the relational-only pilot).
  * Expose a tiny, parameter-only execution surface (`run` / `execute_write`)
    that the `schema` writers build on. Callers pass Cypher + a parameters dict;
    user data NEVER gets string-formatted into the query.

Usage:
    from knesset_osint.graph import GraphClient
    with GraphClient() as gc:
        gc.ping()                       # verify connectivity (raises if down)
        gc.execute_write(cypher, params)

Extending: this class is intentionally generic. New write patterns belong in
`schema.py` (they call `execute_write`/`run`); only add methods here if you need
new *driver-level* behaviour (e.g. multi-database routing via `database=`).
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Optional

from knesset_osint.core.config import settings
from knesset_osint.core.logging import get_logger

logger = get_logger("graph.client")

# Import the driver lazily-tolerantly: the package depends on `neo4j`, but if the
# graph is disabled we still want the module to import cleanly on a box without it.
try:  # pragma: no cover - import guard
    from neo4j import Driver, GraphDatabase
    from neo4j.exceptions import Neo4jError

    _NEO4J_IMPORTED = True
except ImportError:  # pragma: no cover - import guard
    Driver = Any  # type: ignore[assignment,misc]
    GraphDatabase = None  # type: ignore[assignment]
    Neo4jError = Exception  # type: ignore[assignment,misc]
    _NEO4J_IMPORTED = False


class GraphClient:
    """Lifecycle + execution wrapper for the corruption/COI graph.

    The client is a no-op shell whenever `settings.neo4j_enabled` is False OR the
    `neo4j` package is unavailable; in that mode `enabled` is False, no driver is
    created, and read/write helpers log and return empty results. This lets the
    rest of the platform call graph writers unconditionally.
    """

    def __init__(
        self,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        enabled: bool | None = None,
        database: str | None = None,
    ) -> None:
        """Build the client. Defaults are pulled from `settings`.

        Args:
            uri/user/password: override the configured Neo4j connection (tests).
            enabled: force-enable/disable; defaults to `settings.neo4j_enabled`.
            database: target Neo4j database name (Enterprise multi-db). None uses
                the server default ("neo4j"). See extension note at bottom.
        """
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self._database = database

        configured = settings.neo4j_enabled if enabled is None else enabled
        # We are only truly enabled if the operator asked for it AND the driver
        # is importable. Otherwise we degrade to no-op rather than crashing.
        self.enabled: bool = bool(configured) and _NEO4J_IMPORTED
        if configured and not _NEO4J_IMPORTED:  # pragma: no cover - env-dependent
            logger.warning(
                "neo4j_enabled is True but the 'neo4j' package is not importable; "
                "GraphClient is running in no-op mode."
            )

        self._driver: Optional[Driver] = None  # type: ignore[valid-type]

    # ------------------------------------------------------------------ #
    # Driver lifecycle
    # ------------------------------------------------------------------ #
    @property
    def driver(self) -> Optional[Driver]:  # type: ignore[valid-type]
        """Lazily create and cache the driver. Returns None in no-op mode."""
        if not self.enabled:
            return None
        if self._driver is None:
            logger.info("Opening Neo4j driver -> %s (db=%s)", self._uri, self._database or "default")
            # The driver is a pooled, thread-safe object; we build it once.
            self._driver = GraphDatabase.driver(  # type: ignore[union-attr]
                self._uri, auth=(self._user, self._password)
            )
        return self._driver

    def close(self) -> None:
        """Close the underlying driver and release pooled connections."""
        if self._driver is not None:
            logger.info("Closing Neo4j driver")
            self._driver.close()
            self._driver = None

    # Context-manager sugar so callers can `with GraphClient() as gc: ...`.
    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Connectivity
    # ------------------------------------------------------------------ #
    def ping(self) -> bool:
        """Verify connectivity to the server.

        Returns True if reachable, False in no-op mode. Raises the underlying
        driver error if a connection was attempted and failed — callers that
        want a soft check should catch `Exception`.
        """
        return self.verify_connectivity()

    def verify_connectivity(self) -> bool:
        """Alias matching the driver's own method name; see `ping`."""
        if not self.enabled or self.driver is None:
            logger.info("GraphClient disabled; verify_connectivity() -> no-op (False)")
            return False
        # `Driver.verify_connectivity()` performs a real round-trip and raises
        # on failure; we surface a boolean for the happy path.
        self.driver.verify_connectivity()
        logger.info("Neo4j connectivity verified")
        return True

    # ------------------------------------------------------------------ #
    # Execution helpers (parameter-only; the basis for schema.py writers)
    # ------------------------------------------------------------------ #
    def run(
        self,
        cypher: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run read-or-write Cypher in an auto-commit transaction.

        Always pass dynamic values via `parameters` (a dict), NEVER by formatting
        them into `cypher`. Returns a list of result rows as plain dicts so the
        result is materialised before the session closes. No-op mode returns [].
        """
        if not self.enabled or self.driver is None:
            logger.debug("GraphClient disabled; skipping run(): %s", cypher.split("\n", 1)[0])
            return []
        params = parameters or {}
        with self.driver.session(database=self._database) as session:
            result = session.run(cypher, params)
            return [record.data() for record in result]

    def execute_write(
        self,
        cypher: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run write Cypher inside a managed write transaction (auto-retry on
        transient errors via the driver's transaction function).

        Use this for all MERGE-based upserts. Parameter-only, like `run`.
        No-op mode logs and returns [].
        """
        if not self.enabled or self.driver is None:
            logger.debug(
                "GraphClient disabled; skipping execute_write(): %s",
                cypher.split("\n", 1)[0],
            )
            return []
        params = parameters or {}

        def _work(tx: Any) -> list[dict[str, Any]]:
            result = tx.run(cypher, params)
            return [record.data() for record in result]

        with self.driver.session(database=self._database) as session:
            return session.execute_write(_work)


# Extension notes
# ---------------
# * Multi-database (Neo4j Enterprise): pass `database="something"` to the
#   constructor; every session is opened against it. Community edition uses the
#   single default db, so leaving it None is correct for the pilot.
# * Custom auth (e.g. SSO/Kerberos tokens) would change only the `auth=` argument
#   in the `driver` property; nothing else here cares how the driver was built.
# * Higher-level write patterns do NOT belong here — add them to `schema.py`,
#   which composes `execute_write` with parameterized MERGE statements.
