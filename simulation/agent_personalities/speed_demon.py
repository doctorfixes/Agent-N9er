import random

from .base_agent import BaseAgent


class SpeedDemon(BaseAgent):
    specialization = "operations_agent"

    def bid(self, task: dict):
        complexity = self.analyze_task(task)
        confidence = max(0.3, 0.7 - complexity * 0.3 + self.reputation * 0.2)
        price = round(0.05 + complexity * 0.1, 2)
        eta = max(1, round(1 + complexity * 3))

        return {
            "agent_id": self.agent_id,
            "price": price,
            "eta_minutes": eta,
            "confidence": round(min(1.0, confidence), 2),
        }

    def execute(self, task: dict):
        complexity = self.analyze_task(task)
        base_rate = 0.85 - complexity * 0.2
        success = random.random() < base_rate
        duration = max(1, round(2 + complexity * 3))
        return success, duration
