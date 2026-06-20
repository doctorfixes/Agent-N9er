def score(bid):
    return bid["confidence"]


def winner(bids):
    if not bids:
        raise ValueError("Cannot select winner from empty bids list")
    return max(bids, key=score)
