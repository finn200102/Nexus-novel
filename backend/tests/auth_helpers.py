"""Access tokens for tests.

Access tokens must name a live session (``sid``), so a test token comes with a
session row in the test database. ``tests/routes/conftest.py`` points
``current_db`` at the ``db`` fixture's session for every test, so helpers can
call ``bearer_headers(user_id)`` without passing it around.
"""

from app.auth.jwt import create_access_token
from app.models.account import UserSession

current_db = None


def bearer_headers(user_id: int, db=None) -> dict[str, str]:
    db = db or current_db
    if db is None:
        raise RuntimeError("bearer_headers needs the db fixture")
    session = UserSession(user_id=user_id)
    db.add(session)
    db.commit()
    token = create_access_token({"sub": str(user_id), "sid": session.id})
    return {"Authorization": f"Bearer {token}"}
