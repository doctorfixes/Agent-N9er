import random

from .base_agent import BaseAgent


class PrecisionSpecialist(BaseAgent):
    def bid(self, _task: dict):
        return {
            "agent_id": self.agent_id,
            "price": 0.4,
            "eta_minutes": 6,
            "confidence": 0.95,
        }

    def execute(self, _task: dict):
        return random.random() < 0.98, 6
