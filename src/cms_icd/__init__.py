"""Version-aware access to official CMS ICD-10 materials.

The package separates release acquisition from parsing and keeps CM and PCS materials
independently lazy.
"""

from .constants import ICD10_PCS_CHARACTERS
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
    GEMChoiceList,
    GEMDirection,
    GEMEntry,
    GEMMapping,
    GEMProvenance,
    GEMScenario,
    Guideline,
    ICDCMMappingResolution,
    ICDMappingReason,
    ICDMappingStatus,
    ICDPCSMappingResolution,
    InstructionalNote,
    Release,
    Term,
)
from .resolution import (
    resolve_icd9_to_icd10_cm_mapping,
    resolve_icd9_to_icd10_cm_mappings,
    resolve_icd9_to_icd10_pcs_mapping,
    resolve_icd9_to_icd10_pcs_mappings,
)
from .sources import refresh_cms_catalog
from .stores import GEMStore

__all__ = [
    "ICD10_PCS_CHARACTERS",
    "AmbiguousReleaseError",
    "Code",
    "DownloadError",
    "GEMChoiceList",
    "GEMDirection",
    "GEMEntry",
    "GEMKnowledgeBase",
    "GEMMapping",
    "GEMProvenance",
    "GEMScenario",
    "GEMStore",
    "GEMSystemView",
    "Guideline",
    "ICD10CMKnowledgeBase",
    "ICD10KnowledgeBase",
    "ICD10PCSKnowledgeBase",
    "ICDCMMappingResolution",
    "ICDKnowledgeBaseError",
    "ICDMappingReason",
    "ICDMappingStatus",
    "ICDPCSMappingResolution",
    "InstructionalNote",
    "MaterialUnavailableError",
    "ParseError",
    "Release",
    "ReleaseUnavailableError",
    "Term",
    "refresh_cms_catalog",
    "resolve_icd9_to_icd10_cm_mapping",
    "resolve_icd9_to_icd10_cm_mappings",
    "resolve_icd9_to_icd10_pcs_mapping",
    "resolve_icd9_to_icd10_pcs_mappings",
]
