import httpx
async def f(tc):
 async with httpx.AsyncClient()as c:await c.post("http://orchestrator:9000/pipeline",json=tc)
