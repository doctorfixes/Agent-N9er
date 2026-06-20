from fastapi import FastAPI

from agent_personalities import SpeedDemon, PrecisionSpecialist
from runner import run

app = FastAPI()


@app.get("/run")
async def run_simulation(n: int = 10):
    agents = [SpeedDemon("speed"), PrecisionSpecialist("precision")]
    return {"results": run(agents, n=n)}
