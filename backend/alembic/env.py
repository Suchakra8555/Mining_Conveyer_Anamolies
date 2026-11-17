import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402
from app.database.models import Base  # noqa: E402

url = os.environ.get("CONVEYOR_DB_URL", get_settings().db_url)
target_metadata = Base.metadata


def run_migrations_online():
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
