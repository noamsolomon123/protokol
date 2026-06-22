"""Controlled vocabularies.

All enums are `(str, Enum)` so they serialize cleanly to JSON and read well in
the DB. Stored via SQLAlchemy `Enum(native_enum=False)` (a VARCHAR + CHECK),
which keeps migrations portable (Postgres prod, SQLite in tests) and avoids
native-enum ALTER pain when we add values while scaling.
"""

from __future__ import annotations

import enum


class SourceType(str, enum.Enum):
    """Where a record came from. Add a member when onboarding a new source."""

    KNESSET_ODATA = "knesset_odata"          # ParliamentInfo OData V4 (source of truth)
    KNESSET_VOTES = "knesset_votes"          # Votes.svc OData V3 (source of truth)
    OPEN_KNESSET = "open_knesset"            # Hasadna mirror (enrichment only)
    BUDGET_KEY = "budget_key"                # Mafteach HaTaktsiv (future)
    STATE_COMPTROLLER = "state_comptroller"  # future
    COURT = "court"                          # court rulings (future)
    CORPORATIONS_AUTHORITY = "corporations_authority"  # future
    MANUAL = "manual"                        # human-entered, must still carry a source_url


class VoteStance(str, enum.Enum):
    FOR = "for"
    AGAINST = "against"
    ABSTAIN = "abstain"
    ABSENT = "absent"
    NA = "na"


class VoteResult(str, enum.Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class StatementType(str, enum.Enum):
    SPEECH = "speech"
    INTERVIEW = "interview"
    SOCIAL_MEDIA = "social_media"
    PRESS_RELEASE = "press_release"
    PLENUM = "plenum"
    OTHER = "other"


class ActionType(str, enum.Enum):
    ACHIEVEMENT = "achievement"
    BILL_SPONSORED = "bill_sponsored"
    BILL_PASSED = "bill_passed"
    POLICY = "policy"
    APPOINTMENT = "appointment"
    OTHER = "other"


class VerificationStatus(str, enum.Enum):
    """Lifecycle of a statement's fact-check."""

    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NEEDS_REVIEW = "needs_review"


class ContradictionStatus(str, enum.Enum):
    """A flagged statement<->evidence mismatch is always 'needs_review' until a
    human rules on it. The platform never auto-asserts 'lie' / 'corrupt'."""

    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
