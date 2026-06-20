import uuid


class BaseAgent:
    def __init__(self, profile: str):
        self.agent_id = str(uuid.uuid4())
        self.profile = profile
        self.reputation = 0.5

    def update_reputation(self, success: bool, _duration: int):
        self.reputation = min(1, self.reputation + 0.01) if success else max(0, self.reputation - 0.02)
