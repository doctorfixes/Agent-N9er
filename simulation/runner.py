from .task_generator import gen
from .market import winner


def run(agents, n=10):
    out = []
    for _ in range(n):
        task = gen()
        bids = [agent.bid(task) for agent in agents]
        winning_bid = winner(bids)
        selected = [agent for agent in agents if agent.agent_id == winning_bid["agent_id"]][0]
        success, duration = selected.execute(task)
        selected.update_reputation(success, duration)
        out.append(
            {
                "task": task,
                "winner": winning_bid,
                "success": success,
                "duration": duration,
            }
        )
    return out
