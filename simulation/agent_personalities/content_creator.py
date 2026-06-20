import random

from .base_agent import BaseAgent


class ContentCreator(BaseAgent):
    specialization = "content_creator"

    def bid(self, task: dict):
        complexity = self.analyze_task(task)
        confidence = max(0.45, 0.85 - complexity * 0.15 + self.reputation * 0.12)
        price = round(0.08 + complexity * 0.15, 2)
        eta = max(2, round(3 + complexity * 4))

        return {
            "agent_id": self.agent_id,
            "price": price,
            "eta_minutes": eta,
            "confidence": round(min(1.0, confidence), 2),
        }

    def execute(self, task: dict):
        complexity = self.analyze_task(task)
        base_rate = 0.88 - complexity * 0.13
        success = random.random() < base_rate
        duration = max(2, round(3 + complexity * 4))
        return success, duration
