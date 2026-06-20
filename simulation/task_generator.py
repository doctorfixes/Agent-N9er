import uuid


def gen():
    return {"id": str(uuid.uuid4()), "objective": "Task"}
