from .base_agent import BaseAgent
import random
class SpeedDemon(BaseAgent):
 def bid(s,t):return{"agent_id":s.agent_id,"price":0.1,"eta_minutes":1,"confidence":0.7}
 def execute(s,t):return random.random()<0.85,2
