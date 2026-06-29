from sqlalchemy import create_engine, inspect

from bott.shared.schema import init_schema


def test_init_schema_creates_all_tables():
    engine = create_engine("sqlite://")  # in-memory
    init_schema(engine)
    names = set(inspect(engine).get_table_names())
    assert {"jobs", "approvals", "connector_tokens"} <= names


def test_connector_tokens_composite_pk():
    engine = create_engine("sqlite://")
    init_schema(engine)
    pk = inspect(engine).get_pk_constraint("connector_tokens")
    assert set(pk["constrained_columns"]) == {"user_id", "provider"}
