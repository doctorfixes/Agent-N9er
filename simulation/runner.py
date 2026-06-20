import logging

from .task_generator import gen
from .market import winner

logger = logging.getLogger("simulation.runner")


def run(agents, n=10):
    out = []
    for i in range(n):
        task = gen()
        bids = [agent.bid(task) for agent in agents]
        winning_bid = winner(bids)
        selected = next(a for a in agents if a.agent_id == winning_bid["agent_id"])
        success, duration = selected.execute(task)
        selected.update_reputation(success, duration)
        out.append({
            "round": i + 1,
            "task": task,
            "bids": bids,
            "winner": winning_bid,
            "success": success,
            "duration": duration,
        })
    return out
