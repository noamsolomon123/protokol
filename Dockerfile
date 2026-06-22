# ---------------------------------------------------------------------------
# Knesset OSINT — application image.
#
# Builds the FastAPI/ingestion service. The same image runs:
#   * the API        -> uvicorn knesset_osint.main:app
#   * DB migrations  -> alembic upgrade head
#   * CLI ingestion  -> knesset-osint ingest ...
#
# Design notes / how to extend:
#   * Base is python:3.11-slim. The project supports 3.10+, but slim 3.11 is a
#     small, well-maintained runtime. Bump the tag here to change the runtime.
#   * psycopg2-binary (a project dependency) ships manylinux wheels, so a
#     PostgreSQL build toolchain is normally NOT required. We still install a
#     minimal build/runtime layer so the image keeps building if a future dep
#     ever needs to compile psycopg2 from source. Drop build-essential/libpq-dev
#     for a leaner image once you're sure the binary wheel is always used.
#   * The package is src-layout, installed editable (`pip install -e .`), so the
#     importable module is `knesset_osint` and the console script is
#     `knesset-osint` (see pyproject [project.scripts]).
#   * We copy the whole build context in one COPY (filtered by .dockerignore).
#     This is intentional: optional files such as alembic.ini / migrations/ /
#     README.md may be added later by other parts of the project, and a single
#     COPY picks them up automatically without failing when they're absent.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Fail fast, no .pyc clutter, unbuffered logs (so container logs stream live).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System packages:
#   * libpq5         — runtime shared lib psycopg2 links against.
#   * build-essential + libpq-dev — only needed if psycopg2 must compile from
#     source; harmless to keep for forward-compat.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project metadata first so the (slow) dependency install layer is cached
# and only re-runs when pyproject.toml changes, not on every source edit.
COPY pyproject.toml ./

# Pre-create the package dir so the editable install has something to point at
# during the dependency-resolution layer, then bring in the full source tree.
COPY . .

# Editable install resolves the package + its pinned deps from pyproject.toml.
# Editable keeps parity with the dev workflow (the venv is installed editable
# too, per the project contract).
RUN pip install --upgrade pip \
    && pip install -e .

# Document the port the API listens on.
EXPOSE 8000

# Default command runs the API. docker-compose overrides this to first apply
# migrations (see the `api` service `command`). Run a one-off ingest with:
#   docker compose run --rm api knesset-osint ingest person --person-id 965
CMD ["uvicorn", "knesset_osint.main:app", "--host", "0.0.0.0", "--port", "8000"]
