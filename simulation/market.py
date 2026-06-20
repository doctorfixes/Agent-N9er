def score(bid):
    return bid["confidence"]


def winner(bids):
    return max(bids, key=score)
