"""Print schemas, tables and exact row counts so destructive steps can be reviewed."""

from __future__ import annotations

import os

from sqlalchemy import create_engine, func, select, table, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    print(connection.execute(text("SELECT version()")).scalar_one())
    relations = connection.execute(text("""
        SELECT n.nspname AS schema_name, c.relname AS name, c.relkind AS kind
        FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
          AND c.relkind IN ('r', 'v', 'm')
        ORDER BY 1, 2
    """)).all()
    print(f"{len(relations)} user relations")
    for schema_name, name, kind in relations:
        count = ""
        if kind == "r":
            relation = table(name, schema=schema_name)
            count = connection.execute(select(func.count()).select_from(relation)).scalar_one()
        print(f"  {schema_name}.{name} ({kind}) {count}")
engine.dispose()
