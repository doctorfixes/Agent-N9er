import uuid
from task_generator import gen


def test_gen_returns_dict_with_id_and_objective():
    task = gen()
    assert "id" in task
    assert "objective" in task


def test_gen_id_is_valid_uuid():
    task = gen()
    uuid.UUID(task["id"])


def test_gen_produces_unique_ids():
    ids = {gen()["id"] for _ in range(50)}
    assert len(ids) == 50


def test_gen_objective_is_string():
    task = gen()
    assert isinstance(task["objective"], str)
    assert len(task["objective"]) > 0
