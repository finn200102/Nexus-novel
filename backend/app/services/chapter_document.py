"""Versioned, sanitized chapter blocks; originals never become executable markup."""
import hashlib
import json
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED = {"p", "div", "span", "strong", "b", "em", "i", "u", "s", "sup", "sub", "br", "hr",
           "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "ul", "ol", "li",
           "table", "thead", "tbody", "tfoot", "tr", "th", "td", "a", "img"}
BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "ul", "ol", "table", "hr"}
VOID = {"br", "hr", "img"}
DROP = {"script", "style", "iframe", "object", "embed", "svg", "math", "form", "head"}
WRAPPERS = {"div", "aside", "section"}
AUTHOR_NOTE_CLASSES = {"author-note", "author-notes", "author_note", "author_notes", "authors-note", "authors-notes", "authornote", "authornotes"}
NOTE_MARKER = re.compile(r"^\s*(a/n\b|an:|author['’]?s\s+note|note:)", re.I)


def content_version(blocks):
    if any(block.get("role") for block in blocks):
        value = json.dumps([{key: block.get(key) for key in ("html", "role", "role_provenance")} for block in blocks], ensure_ascii=False, separators=(",", ":"))
    else:
        value = "".join(block["html"] for block in blocks)
    return hashlib.sha256(value.encode()).hexdigest()


def story_blocks(document):
    """Narrative evidence excludes commentary, even in older rich documents."""
    blocks = document.get("blocks", [])
    notes = {block["id"] for block in blocks if block.get("role") == "author_note"}
    for ordered in (blocks, list(reversed(blocks))):
        for block in ordered:
            if not NOTE_MARKER.match(block.get("text", "")) and block["id"] not in notes:
                break
            notes.add(block["id"])
    return [block for block in blocks if block["id"] not in notes]


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.muted = 0
        self.parts = []
        self.text = []
        self.fragments = []
        self.kind = "p"
        self.source_stack = []
        self.author_note = False

    def boundary(self):
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        self.flush()

    def flush(self):
        markup = "".join(self.parts).strip()
        text = "".join(self.text).strip()
        if markup and (text or "<hr" in markup or "<img" in markup):
            if self.kind == "p" and not markup.startswith("<p>"):
                markup = f"<p>{markup}</p>"
            self.fragments.append((self.kind, markup, text, self.author_note))
        self.parts, self.text = [], []
        self.kind = "p"

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").lower().split())
        identified_note = tag in (BLOCKS | WRAPPERS) - VOID and not self.muted and (
            bool(classes & AUTHOR_NOTE_CLASSES) or {"notes", "module"}.issubset(classes)
            or attrs.get("data-nexus-role") == "author_note")
        inherited_note = self.source_stack[-1][1] if self.source_stack else False
        next_note = inherited_note or identified_note
        if not self.muted and next_note != self.author_note:
            self.boundary()
            self.author_note = next_note
        if tag not in VOID:
            if len(self.source_stack) >= 256:
                raise ValueError("Chapter markup exceeds the nesting limit")
            self.source_stack.append((tag, next_note, len(self.stack)))
        if tag in DROP:
            self.muted += 1
            return
        if self.muted or (tag not in ALLOWED and tag not in WRAPPERS):
            return
        # Layout wrappers must not turn an entire chapter into one block.
        # Paragraphs/lists/tables inside them retain their own stable anchors.
        if tag in WRAPPERS:
            if not self.stack:
                self.flush()
            else:
                self.text.append("\n")
            return
        if not self.stack and tag in BLOCKS:
            self.flush()
            self.kind = tag
        safe = []
        if tag == "a":
            href = attrs.get("href", "")
            if urlsplit(href).scheme.lower() in {"https", "http", "mailto"} or href.startswith("#"):
                safe.append(f'href="{escape(href, quote=True)}"')
            safe.append('rel="noopener noreferrer"')
        if tag == "img":
            src = attrs.get("src", "")
            # Remote assets require the authenticated fetch broker. Raster data
            # assets from bounded EPUB imports are self-contained and inert.
            if not re.fullmatch(r"data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+", src) or len(src) > 3_000_000:
                self.parts.append(escape(attrs.get("alt", "[Image available on the source]")))
                return
            safe.extend([f'src="{src}"', f'alt="{escape(attrs.get("alt", ""), quote=True)}"'])
        self.parts.append(f"<{tag}{' ' if safe else ''}{' '.join(safe)}{' /' if tag in VOID else ''}>")
        if tag not in VOID:
            self.stack.append(tag)
        elif tag in {"br", "hr"}:
            self.text.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        entry_depth = None
        for index in range(len(self.source_stack) - 1, -1, -1):
            if self.source_stack[index][0] == tag:
                entry_depth = self.source_stack[index][2]
                del self.source_stack[index:]
                break
        if tag in DROP:
            self.muted = max(0, self.muted - 1)
            return
        next_note = self.source_stack[-1][1] if self.source_stack else False
        if not self.muted and next_note != self.author_note:
            self.boundary()
            self.author_note = next_note
        if tag in WRAPPERS:
            if not self.muted and entry_depth is not None:
                while len(self.stack) > entry_depth:
                    self.parts.append(f"</{self.stack.pop()}>")
            if not self.muted and not self.stack:
                self.flush()
            elif not self.muted:
                self.text.append("\n")
            return
        if self.muted or tag not in self.stack:
            return
        while self.stack:
            current = self.stack.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break
        if tag in BLOCKS | {"li", "tr", "td", "th"}:
            self.text.append("\n")
        if not self.stack:
            self.flush()

    def handle_data(self, value):
        if not self.muted:
            self.parts.append(escape(value))
            self.text.append(value)

    def document(self):
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        self.flush()
        seen = {}
        blocks = []
        for kind, markup, text, author_note in self.fragments:
            digest = hashlib.sha256(markup.encode()).hexdigest()[:24]
            duplicate = seen.get(digest, 0)
            seen[digest] = duplicate + 1
            block = {"id": f"b-{digest}-{duplicate}", "kind": kind, "html": markup, "text": text}
            if author_note:
                block.update(role="author_note", role_provenance="source")
            blocks.append(block)
        plain = "\n\n".join(block["text"] for block in blocks)
        version = content_version(blocks)
        return {"schema_version": 1, "content_version": version, "source_format": "html", "blocks": blocks, "plain_text": plain}


def from_html(value):
    if len(value) > 8_000_000:
        raise ValueError("Chapter markup exceeds the size limit")
    parser = _Sanitizer()
    parser.feed(value)
    parser.close()
    return parser.document()


def from_text(value):
    document = from_html("".join(f"<p>{escape(line)}</p>" for line in value.splitlines() if line.strip()))
    document["source_format"] = "text"
    for ordered in (document["blocks"], list(reversed(document["blocks"]))):
        for block in ordered:
            if not NOTE_MARKER.match(block["text"]):
                break
            block.update(role="author_note", role_provenance="heuristic")
    document["content_version"] = content_version(document["blocks"])
    return document
