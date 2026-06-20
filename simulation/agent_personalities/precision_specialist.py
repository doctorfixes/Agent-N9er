import random

from .base_agent import BaseAgent


class PrecisionSpecialist(BaseAgent):
    def bid(self, task: dict):
        complexity = self.analyze_task(task)
        confidence = max(0.5, 0.95 - complexity * 0.1 + self.reputation * 0.1)
        price = round(0.2 + complexity * 0.3, 2)
        eta = max(3, round(6 + complexity * 4))

        return {
            "agent_id": self.agent_id,
            "price": price,
            "eta_minutes": eta,
            "confidence": round(min(1.0, confidence), 2),
        }

    def execute(self, task: dict):
        complexity = self.analyze_task(task)
        base_rate = 0.98 - complexity * 0.1
        success = random.random() < base_rate
        duration = max(3, round(6 + complexity * 4))
        return success, duration
