import random

from .base_agent import BaseAgent


class ResearchAnalyst(BaseAgent):
    specialization = "research_analyst"

    def bid(self, task: dict):
        complexity = self.analyze_task(task)
        confidence = max(0.5, 0.90 - complexity * 0.12 + self.reputation * 0.12)
        price = round(0.15 + complexity * 0.25, 2)
        eta = max(4, round(5 + complexity * 5))

        return {
            "agent_id": self.agent_id,
            "price": price,
            "eta_minutes": eta,
            "confidence": round(min(1.0, confidence), 2),
        }

    def execute(self, task: dict):
        complexity = self.analyze_task(task)
        base_rate = 0.92 - complexity * 0.12
        success = random.random() < base_rate
        duration = max(4, round(5 + complexity * 5))
        return success, duration
