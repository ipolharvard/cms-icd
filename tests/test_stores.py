from __future__ import annotations

import pytest

from cms_icd.models import Guideline
from cms_icd.stores import GuidelineStore


def _store() -> GuidelineStore:
    item = Guideline("I_A_1", "I.A.1", "Example", "Body")
    titles = {"I": "Section", "I.A": "Conventions"}
    return GuidelineStore({"I.A.1": item}, titles)


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
