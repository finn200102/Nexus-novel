"""Private discovery settings use the existing revisioned account settings store."""
import hashlib
import json
from fastapi import HTTPException
from app.models.reader_preference import ReaderPreference, ReaderPreferenceOperation
from app.models.user import User
from app.schemas.discovery_preferences import DiscoveryPreferences

SCOPE = "discovery"


def read(db, user):
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope=SCOPE).first()
    return {"revision": row.revision if row else 0, "values": DiscoveryPreferences.model_validate(row.values if row else {}).model_dump()}


def write(db, user, value):
    db.query(User).filter_by(id=user.id).with_for_update().one()
    fingerprint = hashlib.sha256(json.dumps({"scope": SCOPE, **value.model_dump()}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = db.query(ReaderPreferenceOperation).filter_by(user_id=user.id, operation_id=value.operation_id).first()
    if receipt:
        if receipt.fingerprint != fingerprint:
            raise HTTPException(409, detail="This operation id belongs to a different preferences change")
        return receipt.response
    current = read(db, user)
    if current["revision"] != value.expected_revision:
        raise HTTPException(409, detail={"message": "Discovery preferences changed on another device", "current": current})
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope=SCOPE).first()
    if row is None:
        row = ReaderPreference(user_id=user.id, scope=SCOPE, revision=0)
        db.add(row)
    row.values = value.values.model_dump(); row.revision += 1
    result = {"revision": row.revision, "values": row.values}
    db.add(ReaderPreferenceOperation(user_id=user.id, operation_id=value.operation_id, fingerprint=fingerprint, response=result))
    db.commit()
    return result
