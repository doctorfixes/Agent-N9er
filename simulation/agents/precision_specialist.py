from .base_agent import BaseAgent
import random
class PrecisionSpecialist(BaseAgent):
 def bid(s,t):return{"agent_id":s.agent_id,"price":0.4,"eta_minutes":6,"confidence":0.95}
 def execute(s,t):return random.random()<0.98,6
