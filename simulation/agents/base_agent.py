import uuid
class BaseAgent:
 def __init__(s,p):s.agent_id=str(uuid.uuid4());s.p=p;s.r=0.5
 def update_reputation(s,x,d):s.r=min(1,s.r+0.01)if x else max(0,s.r-0.02)
