import random

from .base_agent import BaseAgent


class BalancedGeneralist(BaseAgent):
    specialization = "generalist"

    def bid(self, task: dict):
        complexity = self.analyze_task(task)
        confidence = max(0.4, 0.8 - complexity * 0.15 + self.reputation * 0.15)
        price = round(0.1 + complexity * 0.2, 2)
        eta = max(2, round(3 + complexity * 3))

        return {
            "agent_id": self.agent_id,
            "price": price,
            "eta_minutes": eta,
            "confidence": round(min(1.0, confidence), 2),
        }

    def execute(self, task: dict):
        complexity = self.analyze_task(task)
        base_rate = 0.90 - complexity * 0.15
        success = random.random() < base_rate
        duration = max(2, round(3 + complexity * 3))
        return success, duration
