from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pid_provider.models import PidProviderXML


@pytest.mark.parametrize(
    "min_rate,scores,selected,tied,secondary,rejected",
    [
        (0.65, [0.95, 0.20], 1, [], [], [2]),
        (0.65, [0.65, 0.64], None, [], [], [1, 2]),
        (0.60, [0.65, 0.64], 1, [], [2], []),
        (0.65, [0.90, 0.90, 0.75], 2, [2, 1], [3], []),
        (0.65, [0.95, 0.85, 0.75], 1, [], [2, 3], []),
    ],
)
def test_classifies_scores_and_exposes_ties(
    settings, min_rate, scores, selected, tied, secondary, rejected
):
    settings.PID_PROVIDER_MIN_RATE = min_rate
    candidates = [
        SimpleNamespace(
            id=index, updated=datetime(2026, 1, index),
            data={"id": index}, data_to_compare={"score": score},
        )
        for index, score in enumerate(scores, start=1)
    ]
    with patch(
        "pid_provider.models.compare",
        side_effect=lambda data, _: {"percentual_score": data["score"]},
    ):
        result = PidProviderXML.get_best_match(candidates, {})

    assert getattr(result.get("registered"), "id", None) == selected
    for key, expected in (
        ("multiple_matched", tied), ("matched", secondary), ("unmatched", rejected)
    ):
        entries = result.get(key, [])
        assert [item["data"]["id"] for item in entries] == expected
        for item in entries:
            assert item["response"]["percentual_score"] == scores[item["data"]["id"] - 1]


def test_selection_exposes_ambiguity_from_real_comparison():
    candidates = [
        SimpleNamespace(
            id=index, updated=datetime(2026, 1, index),
            data={"id": index}, data_to_compare={"article_titles": ["Mesmo título"]},
        )
        for index in (1, 2)
    ]
    adapter = MagicMock()
    adapter.get_data_to_compare.return_value = {"article_titles": ["Mesmo título"]}

    result = PidProviderXML.select_record(adapter, [("ids", candidates)])

    assert [item["data"]["id"] for item in result["multiple_matched_items"]["ids"]] == [2, 1]
    assert "matched_items" not in result
