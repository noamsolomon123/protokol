"""Import every model so `Base.metadata` is complete and string-based
relationships resolve. Alembic and `create_all` rely on importing this package.
"""

from knesset_osint.db.base import Base
from knesset_osint.models.action import Action
from knesset_osint.models.bill import Bill, BillSponsorship
from knesset_osint.models.enums import (
    ActionType,
    ContradictionStatus,
    SourceType,
    StatementType,
    VerificationStatus,
    VoteResult,
    VoteStance,
)
from knesset_osint.models.politician import Politician
from knesset_osint.models.role import Role
from knesset_osint.models.statement import Statement
from knesset_osint.models.vote import Vote, VoteEvent
from knesset_osint.models.verification import Contradiction

__all__ = [
    "Base",
    "Politician",
    "Role",
    "Bill",
    "BillSponsorship",
    "VoteEvent",
    "Vote",
    "Statement",
    "Action",
    "Contradiction",
    "SourceType",
    "VoteStance",
    "VoteResult",
    "StatementType",
    "ActionType",
    "VerificationStatus",
    "ContradictionStatus",
]
