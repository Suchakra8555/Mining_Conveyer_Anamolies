from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models import Base


def make_engine(url: str):
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    eng = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragma(dbapi, _):
            cur = dbapi.cursor(); cur.execute("PRAGMA journal_mode=WAL"); cur.execute("PRAGMA synchronous=NORMAL"); cur.close()
    return eng


def init_db(engine):
    Base.metadata.create_all(engine)   # Alembic migrations in backend/alembic mirror this schema


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory):
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
