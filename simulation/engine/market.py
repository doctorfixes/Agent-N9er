def score(b):return b["confidence"]
def winner(bs):return max(bs,key=score)
