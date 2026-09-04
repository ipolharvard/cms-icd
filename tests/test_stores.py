from __future__ import annotations

from datetime import date

import pytest

from cms_icd.models import (
    Code,
    GEMDirection,
    GEMEntry,
    GEMProvenance,
    Guideline,
    Node,
    Release,
    Term,
)
from cms_icd.stores import GEMStore, GuidelineStore, IndexStore, TabularStore


def _guideline() -> Guideline:
    return Guideline("I_A_1", "I.A.1", "Example", "Body")


def _store() -> GuidelineStore:
    titles = {"I": "Section", "I.A": "Conventions"}
    return GuidelineStore({"I.A.1": _guideline()}, titles)


def test_guideline_store_membership_agrees_with_lookup_len_iteration() -> None:
    store = _store()

    leaf = "I.A.1"
    section_keys = ("I", "I.A")
    unknown = "I.B"

    # Leaf keys are members, returned by item access, and covered by len/iteration.
    assert leaf in store
    assert store[leaf].id == "I_A_1"
    assert list(store) == [leaf]
    assert set(store) == {leaf}
    assert len(store) == 1

    # Title-only section keys are not members and item access raises KeyError.
    for key in section_keys:
        assert key not in store
        assert key not in list(store)
        with pytest.raises(KeyError):
            store[key]

    # Unknown keys agree with section keys.
    assert unknown not in store
    assert unknown not in list(store)
    with pytest.raises(KeyError):
        store[unknown]

    # Membership, iteration, and length agree over the full key space.
    keys = (*section_keys, leaf, unknown, "II")
    assert {key for key in keys if key in store} == set(store)
    assert len(store) == len(set(store))


_GEM_ROW = GEMEntry("0010", "A001", False, False, False, 1, 1)
_GEM_RELEASE = Release(2025, date(2024, 10, 1))
_GEM_PROVENANCE = {"0010": GEMProvenance(_GEM_RELEASE, _GEM_RELEASE, _GEM_RELEASE)}


def _gem_store(
    system: str = "cm",
    direction: GEMDirection = GEMDirection.ICD9_TO_ICD10,
    release: Release | None = _GEM_RELEASE,
    provenance: dict[str, GEMProvenance] | None = _GEM_PROVENANCE,
) -> GEMStore:
    return GEMStore(
        {"0010": (_GEM_ROW,)},
        system=system,
        direction=direction,
        release=release,
        provenance=provenance,
    )


def test_gem_store_equality_considers_identifying_metadata() -> None:
    base = _gem_store()
    assert base == _gem_store()

    # Synthetic stores differing only in identifying metadata (or items) are unequal.
    for store in (
        _gem_store(system="pcs"),
        _gem_store(direction=GEMDirection.ICD10_TO_ICD9),
        _gem_store(release=None),
        _gem_store(provenance={}),
        GEMStore(
            {"0010": (GEMEntry("0010", "A002", False, False, False, 1, 1),)},
            system="cm",
            direction=GEMDirection.ICD9_TO_ICD10,
            release=_GEM_RELEASE,
            provenance=_GEM_PROVENANCE,
        ),
    ):
        assert base != store
        assert store != base

    # A store never equals a bare mapping or a non-mapping with the same items.
    assert base != {"0010": (_GEM_ROW,)}
    assert {"0010": (_GEM_ROW,)} != base
    assert base != ("0010",)


def _tabular_nodes() -> tuple[Node, Code]:
    root = Node("cm", "cm", children_ids=("I10",))
    code = Code("I10", "I10", "Essential hypertension", parent_id="cm")
    return root, code


def _tabular_store(
    code_lookup: dict[str, str] | None = None,
    roots: tuple[str, ...] = ("cm",),
) -> TabularStore:
    root, code = _tabular_nodes()
    return TabularStore(
        {"cm": root, "I10": code},
        {"I10": "I10"} if code_lookup is None else code_lookup,
        roots,
    )


def test_tabular_store_equality_considers_lookup_and_roots() -> None:
    base = _tabular_store()
    assert base == _tabular_store()

    # Synthetic stores differing only in lookup, roots, or items are unequal.
    for store in (
        _tabular_store(code_lookup={"I10": "I10_node"}),
        _tabular_store(roots=()),
        TabularStore(
            {
                "cm": Node("cm", "cm", children_ids=("I10",)),
                "I10": Code("I10", "I10", "Other diagnosis", parent_id="cm"),
            },
            {"I10": "I10"},
            ("cm",),
        ),
    ):
        assert base != store
        assert store != base

    root, code = _tabular_nodes()
    assert base != {"cm": root, "I10": code}
    assert {"cm": root, "I10": code} != base


def test_guideline_store_equality_considers_titles_and_preambles() -> None:
    titles = {"I": "Section", "I.A": "Conventions"}
    preambles = {"I": "Introduction"}
    base = GuidelineStore({"I.A.1": _guideline()}, titles, preambles)
    assert base == GuidelineStore({"I.A.1": _guideline()}, titles, preambles)

    # Synthetic stores differing only in titles, preambles, or items are unequal.
    for store in (
        GuidelineStore({"I.A.1": _guideline()}, {"I": "Different"}, preambles),
        GuidelineStore({"I.A.1": _guideline()}, titles, {"I": "Different"}),
        GuidelineStore(
            {"I.A.1": Guideline("I_A_1", "I.A.1", "Other", "Body")},
            titles,
            preambles,
        ),
    ):
        assert base != store
        assert store != base

    assert base != {"I.A.1": _guideline()}
    assert {"I.A.1": _guideline()} != base


def test_index_store_equality_is_value_based() -> None:
    main = Term("A", "A", children_ids=("A.1",))
    child = Term("A.1", "A.1", parent_id="A")
    base = IndexStore({"A": main, "A.1": child})
    assert base == IndexStore({"A": main, "A.1": child})
    assert base != IndexStore({"A": main, "A.1": Term("A.1", "Other", parent_id="A")})

    bare = {"A": main, "A.1": child}
    assert base != bare
    assert bare != base


def test_stores_are_not_hashable() -> None:
    for store in (
        _gem_store(),
        _tabular_store(),
        GuidelineStore({"I.A.1": _guideline()}),
        IndexStore({"A": Term("A", "A")}),
    ):
        with pytest.raises(TypeError):
            hash(store)
