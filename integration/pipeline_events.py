import httpx
async def s():
 async with httpx.AsyncClient()as c:
  t=(await c.get("http://bidding-marketplace:8300/feed")).json()
  a=(await c.get("http://reputation-ledger:8500/ledger")).json()
  return{"tasks":t,"agents":a}
