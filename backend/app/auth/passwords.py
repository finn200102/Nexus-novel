import bcrypt

# bcrypt's default cost; tests lower it to keep the suite fast.
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    # Very old rows hold a PostgreSQL hex dump of the hash bytes; those
    # accounts need an administrator password reset.
    if not stored_hash or stored_hash.startswith("\\x"):
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False
