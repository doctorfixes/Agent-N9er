import random

from simulation.agent_personalities import SpeedDemon, PrecisionSpecialist, BalancedGeneralist
from simulation.agent_personalities.base_agent import BaseAgent


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

    def test_analyze_task_complexity(self):
        agent = BaseAgent("test")
        simple = agent.analyze_task({"objective": "fix bug"})
        complex_task = agent.analyze_task({"objective": "review and refactor the entire auth module for security compliance across all services"})
        assert complex_task > simple

    def test_stats(self):
        agent = BaseAgent("test")
        agent.update_reputation(True, 1)
        agent.update_reputation(True, 1)
        agent.update_reputation(False, 1)
        stats = agent.stats()
        assert stats["completed"] == 2
        assert stats["failed"] == 1
        assert stats["profile"] == "test"


class TestSpeedDemon:
    def test_bid_structure(self):
        agent = SpeedDemon("speed")
        bid = agent.bid({"id": "t1", "objective": "test task"})
        assert bid["agent_id"] == agent.agent_id
        assert "price" in bid
        assert "eta_minutes" in bid
        assert "confidence" in bid

    def test_bid_varies_by_task(self):
        agent = SpeedDemon("speed")
        simple_bid = agent.bid({"objective": "fix"})
        complex_bid = agent.bid({"objective": "review and refactor the entire authentication module for compliance"})
        assert simple_bid["confidence"] != complex_bid["confidence"]

    def test_execute_returns_bool_and_duration(self):
        agent = SpeedDemon("speed")
        success, duration = agent.execute({"objective": "test"})
        assert isinstance(success, bool)
        assert isinstance(duration, int)

    def test_execute_success_rate_reasonable(self):
        random.seed(42)
        agent = SpeedDemon("speed")
        results = [agent.execute({"objective": "test"})[0] for _ in range(1000)]
        rate = sum(results) / len(results)
        assert 0.60 < rate < 0.95


class TestPrecisionSpecialist:
    def test_bid_structure(self):
        agent = PrecisionSpecialist("precision")
        bid = agent.bid({"objective": "test"})
        assert bid["agent_id"] == agent.agent_id
        assert "price" in bid
        assert "eta_minutes" in bid
        assert "confidence" in bid

    def test_higher_confidence_than_speed(self):
        speed = SpeedDemon("speed")
        precision = PrecisionSpecialist("precision")
        task = {"objective": "deploy staging"}
        assert precision.bid(task)["confidence"] > speed.bid(task)["confidence"]

    def test_execute_returns_bool_and_duration(self):
        agent = PrecisionSpecialist("precision")
        success, duration = agent.execute({"objective": "test"})
        assert isinstance(success, bool)
        assert isinstance(duration, int)

    def test_execute_success_rate_high(self):
        random.seed(42)
        agent = PrecisionSpecialist("precision")
        results = [agent.execute({"objective": "test"})[0] for _ in range(1000)]
        rate = sum(results) / len(results)
        assert 0.85 < rate < 1.0


class TestBalancedGeneralist:
    def test_bid_structure(self):
        agent = BalancedGeneralist("balanced")
        bid = agent.bid({"objective": "test"})
        assert "agent_id" in bid
        assert "price" in bid
        assert "confidence" in bid

    def test_confidence_between_speed_and_precision(self):
        speed = SpeedDemon("speed")
        balanced = BalancedGeneralist("balanced")
        precision = PrecisionSpecialist("precision")
        task = {"objective": "deploy staging"}
        assert speed.bid(task)["confidence"] < balanced.bid(task)["confidence"]
        assert balanced.bid(task)["confidence"] < precision.bid(task)["confidence"]
