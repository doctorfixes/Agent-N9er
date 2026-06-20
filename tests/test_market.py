import pytest
from simulation.market import score, winner


def test_score_returns_confidence():
    assert score({"confidence": 0.7}) == 0.7


def test_winner_selects_highest_confidence():
    bids = [
        {"agent_id": "a", "confidence": 0.5},
        {"agent_id": "b", "confidence": 0.9},
        {"agent_id": "c", "confidence": 0.3},
    ]
    assert winner(bids)["agent_id"] == "b"


def test_winner_single_bid():
    bids = [{"agent_id": "only", "confidence": 0.1}]
    assert winner(bids)["agent_id"] == "only"


def test_winner_tie_returns_one():
    bids = [
        {"agent_id": "a", "confidence": 0.8},
        {"agent_id": "b", "confidence": 0.8},
    ]
    result = winner(bids)
    assert result["agent_id"] in ("a", "b")


def test_winner_empty_bids_raises():
    with pytest.raises(ValueError):
        winner([])
