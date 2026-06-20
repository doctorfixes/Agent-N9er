import uuid


class BaseAgent:
    specialization = "generalist"

    def __init__(self, profile: str):
        self.agent_id = str(uuid.uuid4())
        self.profile = profile
        self.reputation = 0.5
        self.tasks_completed = 0
        self.tasks_failed = 0

    def update_reputation(self, success: bool, duration: int):
        if success:
            self.reputation = min(1.0, self.reputation + 0.01)
            self.tasks_completed += 1
        else:
            self.reputation = max(0.0, self.reputation - 0.02)
            self.tasks_failed += 1

    def analyze_task(self, task: dict) -> float:
        objective = task.get("objective", "")
        words = objective.lower().split()
        complexity = min(len(words) / 10.0, 1.0)
        return complexity

    def bid(self, task: dict) -> dict:
        raise NotImplementedError

    def execute(self, task: dict) -> tuple:
        raise NotImplementedError

    def stats(self) -> dict:
        total = self.tasks_completed + self.tasks_failed
        return {
            "agent_id": self.agent_id,
            "profile": self.profile,
            "specialization": self.specialization,
            "reputation": round(self.reputation, 3),
            "completed": self.tasks_completed,
            "failed": self.tasks_failed,
            "win_rate": round(self.tasks_completed / total, 3) if total > 0 else 0,
        }
