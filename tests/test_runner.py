import sys
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(root))

from simulation.agent_personalities import SpeedDemon, PrecisionSpecialist
from simulation.runner import run


def _make_agents():
    return [SpeedDemon("speed"), PrecisionSpecialist("precision")]


def test_run_returns_correct_count():
    results = run(_make_agents(), n=5)
    assert len(results) == 5


def test_run_default_count_is_10():
    results = run(_make_agents())
    assert len(results) == 10


def test_run_result_structure():
    results = run(_make_agents(), n=1)
    r = results[0]
    assert "task" in r
    assert "winner" in r
    assert "success" in r
    assert "duration" in r


def test_run_winner_is_valid_agent():
    agents = _make_agents()
    agent_ids = {a.agent_id for a in agents}
    results = run(agents, n=3)
    for r in results:
        assert r["winner"]["agent_id"] in agent_ids


def test_run_updates_reputation():
    agents = _make_agents()
    initial_reps = [a.reputation for a in agents]
    run(agents, n=20)
    changed = any(a.reputation != init for a, init in zip(agents, initial_reps))
    assert changed


def test_precision_specialist_wins_over_speed_demon():
    agents = _make_agents()
    results = run(agents, n=5)
    precision_id = agents[1].agent_id
    for r in results:
        assert r["winner"]["agent_id"] == precision_id
