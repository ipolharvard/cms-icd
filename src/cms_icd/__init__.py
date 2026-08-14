"""Version-aware access to official CMS ICD-10 materials.

The package separates release acquisition from parsing and keeps CM and PCS materials
independently lazy.
"""

from .exceptions import (
    AmbiguousReleaseError,
    DownloadError,
    ICDKnowledgeBaseError,
    MaterialUnavailableError,
    ParseError,
    ReleaseUnavailableError,
)
from .gems import GEMKnowledgeBase, GEMSystemView
from .knowledge_base import (
    ICD10CMKnowledgeBase,
    ICD10KnowledgeBase,
    ICD10PCSKnowledgeBase,
)
from .models import (
    Code,
    GEMDirection,
    GEMEntry,
    Guideline,
    InstructionalNote,
    Release,
    Term,
)
from .stores import GEMStore

__all__ = [
    "AmbiguousReleaseError",
    "Code",
    "DownloadError",
    "GEMDirection",
    "GEMEntry",
    "GEMKnowledgeBase",
    "GEMStore",
    "GEMSystemView",
    "Guideline",
    "ICD10CMKnowledgeBase",
    "ICD10KnowledgeBase",
    "ICD10PCSKnowledgeBase",
    "ICDKnowledgeBaseError",
    "InstructionalNote",
    "MaterialUnavailableError",
    "ParseError",
    "Release",
    "ReleaseUnavailableError",
    "Term",
]
