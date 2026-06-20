import random

from .base_agent import BaseAgent


class SpeedDemon(BaseAgent):
    def bid(self, _task: dict):
        return {
            "agent_id": self.agent_id,
            "price": 0.1,
            "eta_minutes": 1,
            "confidence": 0.7,
        }

    def execute(self, _task: dict):
        return random.random() < 0.85, 2
