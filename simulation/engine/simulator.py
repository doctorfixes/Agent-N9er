from .task_generator import gen
from .market import winner
def run(agents,n=10):
 out=[]
 for _ in range(n):
  t=gen()
  bs=[a.bid(t)for a in agents]
  w=winner(bs)
  a=[x for x in agents if x.agent_id==w["agent_id"]][0]
  s,d=a.execute(t)
  a.update_reputation(s,d)
  out.append({"task":t,"winner":w,"success":s,"duration":d})
 return out
