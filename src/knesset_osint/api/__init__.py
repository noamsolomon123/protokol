"""HTTP API package: FastAPI routers, dependencies, and request schemas.

The app factory lives at :func:`knesset_osint.main.create_app`, which wires the
routers from :mod:`knesset_osint.api.routers`. Shared request-time dependencies
(DB session, pagination) live in :mod:`knesset_osint.api.deps`.
"""
