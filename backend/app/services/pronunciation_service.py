"""Private literal pronunciation snapshots. Story content is never rewritten."""
import hashlib
import json
import re

from fastapi import HTTPException
from app.models.reader_preference import ReaderPreference, ReaderPreferenceOperation
from app.models.user import User
from app.routers.reader_tools import own_novel

PIPELINE_VERSION = "literal-pronunciation-v1"
MAX_AUDIO_SPOKEN_UTF16 = 2_000_000
MAX_AUDIO_PARTS = 10_000


class AudioPlanningLimitError(ValueError):
    def __init__(self):
        super().__init__("This chapter exceeds the narration limit (2,000,000 spoken characters or 10,000 parts). Shorten or disable pronunciation entries, or split the chapter before trying again.")


def ensure_speech_budget(document, title, rules, include_author_notes=False):
    # Stream normalized literal copies into a counter, never an expanded
    # chapter string. A hostile expansion fails before allocating its units.
    pattern = matcher(rules)
    mapping = {rule["source"]: rule["spoken"] for rule in rules}
    total = 0
    texts = [title or "", *(block.get("text", "") for block in document.get("blocks", []) if include_author_notes or block.get("role") != "author_note")]
    for text in texts:
        had_text, pending_space = False, False
        def feed(fragment):
            nonlocal total, had_text, pending_space
            for token in re.finditer(r"\s+|\S+", fragment):
                raw = token.group()
                if raw.isspace():
                    pending_space = had_text
                else:
                    total += len(raw.encode("utf-16-le")) // 2 + int(pending_space)
                    had_text, pending_space = True, False
                    if total > MAX_AUDIO_SPOKEN_UTF16:
                        raise AudioPlanningLimitError()
        previous = 0
        for match in pattern.finditer(text) if pattern else []:
            feed(text[previous:match.start()]); feed(mapping[match.group()]); previous = match.end()
        feed(text[previous:])


def canonical(rules):
    return sorted(({"source": rule["source"], "spoken": rule["spoken"]} for rule in rules), key=lambda rule: rule["source"])


def version(rules):
    if not rules:
        return None
    value = {"pipeline": PIPELINE_VERSION, "rules": canonical(rules)}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def snapshot(db, user_id, novel_id=None):
    global_row = db.query(ReaderPreference).filter_by(user_id=user_id, scope="pronunciation").first()
    global_rules = (global_row.values or {}).get("rules", []) if global_row else []
    row = global_row if novel_id is None else db.query(ReaderPreference).filter_by(user_id=user_id, scope=f"pronunciation:{novel_id}").first()
    values = row.values or {} if row else {}
    rules = canonical(values.get("rules", []))
    inherit = bool(values.get("inherit_account", True)) if novel_id is not None else False
    effective = {rule["source"]: rule for rule in (global_rules if inherit else [])}
    effective.update({rule["source"]: rule for rule in rules})
    effective_rules = canonical(effective.values())
    return {"scope": f"pronunciation:{novel_id}" if novel_id is not None else "pronunciation", "revision": row.revision if row else 0,
            "rules": rules, "account_rules": canonical(global_rules) if novel_id is not None else [], "inherit_account": inherit, "effective_rules": effective_rules, "effective_version": version(effective_rules)}


def write(db, user, value, novel_id=None):
    if novel_id is not None:
        own_novel(db, user, novel_id)
    db.query(User).filter_by(id=user.id).with_for_update().first()
    scope = f"pronunciation:{novel_id}" if novel_id is not None else "pronunciation"
    values = {"rules": canonical([rule.model_dump() for rule in value.rules]), "inherit_account": value.inherit_account if novel_id is not None else False}
    payload = {"scope": scope, "values": values, "expected_revision": value.expected_revision}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = db.query(ReaderPreferenceOperation).filter_by(user_id=user.id, operation_id=value.operation_id).first()
    if prior:
        if prior.fingerprint != fingerprint:
            raise HTTPException(409, "This operation id belongs to another settings change")
        return prior.response
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope=scope).first()
    if value.expected_revision != (row.revision if row else 0):
        raise HTTPException(409, detail={"message": "Pronunciation settings changed on another device", "current": snapshot(db, user.id, novel_id)})
    if row is None:
        row = ReaderPreference(user_id=user.id, novel_id=novel_id, scope=scope, revision=0)
        db.add(row)
    row.values = values
    row.revision += 1
    db.flush()
    response = snapshot(db, user.id, novel_id)
    db.add(ReaderPreferenceOperation(user_id=user.id, operation_id=value.operation_id, fingerprint=fingerprint, response=response))
    db.commit()
    return response


def matcher(rules):
    return re.compile("|".join(re.escape(rule["source"]) for rule in sorted(rules, key=lambda rule: -len(rule["source"])))) if rules else None


def apply(text, rules):
    pattern = matcher(rules)
    mapping = {rule["source"]: rule["spoken"] for rule in rules}
    return pattern.sub(lambda match: mapping[match.group()], text) if pattern else text


def pronounced_chunks(text, maximum, rules):
    """Bounded streaming units retain their exact original source spans."""
    pattern = matcher(rules)
    mapping = {rule["source"]: rule["spoken"] for rule in rules}

    def normal(start, end):
        for match in re.finditer(r"\s+|\S+", text[start:end]):
            raw, at = match.group(), start + match.start()
            if raw.isspace():
                yield " ", at, at + len(raw)
            else:
                piece, piece_start, size = "", at, 0
                for index, char in enumerate(raw):
                    width = len(char.encode("utf-16-le")) // 2
                    if size + width > maximum and piece:
                        yield piece, piece_start, at + index
                        piece, piece_start, size = "", at + index, 0
                    piece += char; size += width
                if piece:
                    yield piece, piece_start, at + len(raw)

    def units():
        previous = 0
        for match in pattern.finditer(text) if pattern else []:
            yield from normal(previous, match.start())
            yield " ".join(mapping[match.group()].split()), match.start(), match.end()
            previous = match.end()
        yield from normal(previous, len(text))

    buffer, size = [], 0
    def render():
        trimmed = len(buffer)
        while trimmed and buffer[trimmed - 1][0] == " ":
            trimmed -= 1
        return ("".join(unit[0] for unit in buffer[:trimmed]), buffer[0][1], buffer[trimmed - 1][2])
    for unit in units():
        width = len(unit[0].encode("utf-16-le")) // 2
        if width > maximum:
            raise ValueError("A pronunciation is longer than this provider's passage limit")
        if size + width > maximum and buffer:
            yield render(); buffer, size = [], 0
        if not buffer and unit[0] == " ":
            continue
        buffer.append(unit); size += width
    if buffer:
        yield render()
