import random

from agent_personalities import SpeedDemon, PrecisionSpecialist
from agent_personalities.base_agent import BaseAgent


class TestBaseAgent:
    def test_init_sets_profile(self):
        agent = BaseAgent("test")
        assert agent.profile == "test"

    def test_init_sets_default_reputation(self):
        agent = BaseAgent("test")
        assert agent.reputation == 0.5

    def test_init_generates_uuid(self):
        a = BaseAgent("x")
        b = BaseAgent("x")
        assert a.agent_id != b.agent_id

    def test_reputation_increases_on_success(self):
        agent = BaseAgent("test")
        before = agent.reputation
        agent.update_reputation(True, 5)
        assert agent.reputation == before + 0.01

    def test_reputation_decreases_on_failure(self):
        agent = BaseAgent("test")
        before = agent.reputation
        agent.update_reputation(False, 5)
        assert agent.reputation == before - 0.02

    def test_reputation_capped_at_1(self):
        agent = BaseAgent("test")
        agent.reputation = 0.999
        agent.update_reputation(True, 1)
        assert agent.reputation == 1.0

    def test_reputation_floored_at_0(self):
        agent = BaseAgent("test")
        agent.reputation = 0.005
        agent.update_reputation(False, 1)
        assert agent.reputation == 0.0


class TestSpeedDemon:
    def test_bid_structure(self):
        agent = SpeedDemon("speed")
        bid = agent.bid({"id": "t1", "objective": "test"})
        assert bid["agent_id"] == agent.agent_id
        assert "price" in bid
        assert "eta_minutes" in bid
        assert "confidence" in bid

    def test_bid_values(self):
        agent = SpeedDemon("speed")
        bid = agent.bid({})
        assert bid["price"] == 0.1
        assert bid["eta_minutes"] == 1
        assert bid["confidence"] == 0.7

    def test_execute_returns_bool_and_duration(self):
        agent = SpeedDemon("speed")
        success, duration = agent.execute({})
        assert isinstance(success, bool)
        assert duration == 2

    def test_execute_success_rate_approximately_85_percent(self):
        random.seed(42)
        agent = SpeedDemon("speed")
        results = [agent.execute({})[0] for _ in range(1000)]
        rate = sum(results) / len(results)
        assert 0.80 < rate < 0.90


class TestPrecisionSpecialist:
    def test_bid_structure(self):
        agent = PrecisionSpecialist("precision")
        bid = agent.bid({})
        assert bid["agent_id"] == agent.agent_id
        assert "price" in bid
        assert "eta_minutes" in bid
        assert "confidence" in bid

    def test_bid_values(self):
        agent = PrecisionSpecialist("precision")
        bid = agent.bid({})
        assert bid["price"] == 0.4
        assert bid["eta_minutes"] == 6
        assert bid["confidence"] == 0.95

    def test_execute_returns_bool_and_duration(self):
        agent = PrecisionSpecialist("precision")
        success, duration = agent.execute({})
        assert isinstance(success, bool)
        assert duration == 6

    def test_execute_success_rate_approximately_98_percent(self):
        random.seed(42)
        agent = PrecisionSpecialist("precision")
        results = [agent.execute({})[0] for _ in range(1000)]
        rate = sum(results) / len(results)
        assert 0.95 < rate < 1.0
