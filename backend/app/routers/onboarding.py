"""Explicit, private demo reading. No catalog, source, or model requests."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models import Chapter, Library, Novel, User
from app.models.chapter import ContentStatus
from app.services.chapter_document import from_html

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

# Original Nexus fixtures, dedicated to the public domain under CC0.
# Stable keys make retries and repeated selections safe.
DEMO_STORIES = (
    ("lantern", "The Lantern Keeper", (
        ("An unexpected light", "<p>Mara kept the last lighthouse on a coast without ships. Every evening she climbed the hundred steps, polished the lens, and lit the lamp.</p><p>One autumn night, a second light answered from the sea.</p><p>It blinked three times, paused, then blinked once more. Mara found her grandfather’s notebook beneath the workbench. Beside the same pattern he had written: <em>Leave the door unlocked.</em></p><hr><p>At dawn, someone knocked.</p>"),
        ("The visitor", "<p>The visitor carried no suitcase, only a brass compass whose needle pointed toward the lamp.</p><p>‘I think this belongs to you,’ she said.</p><p>Mara opened the notebook to its final page. A small envelope had been pressed between the sheets. Inside was a photograph of two children standing beside this very door.</p><p>One was her grandfather. The other was the visitor, smiling exactly as she smiled now.</p>"),
    )),
    ("garden", "A Garden for the Moon", (
        ("Seeds", "<p>Every spring, Theo planted a row of flowers that nobody else could see. His neighbors called the strip beside the wall an empty patch.</p><p>Then a child stopped at the gate and asked why the flowers were shining.</p><p>‘They only open in moonlight,’ Theo said.</p><p>She considered this. ‘Then we should plant some where the moon can see them.’</p><p>They carried the remaining seeds to the hill. By summer, the path home looked like a river of little stars.</p>"),
    )),
)


class DemoRequest(BaseModel):
    library_id: int = Field(ge=1)


class DemoStory(BaseModel):
    novel_id: int
    title: str
    chapter_number: int = 1
    created: bool


class DemoResponse(BaseModel):
    library_id: int
    stories: list[DemoStory]
    license: str = "CC0-1.0"


@router.post("/demo", response_model=DemoResponse)
def add_demo(request: DemoRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Serialize repeat clicks from separate devices without duplicate entries.
    db.query(User).filter_by(id=user.id).with_for_update().one()
    library = db.query(Library).filter_by(id=request.library_id, user_id=user.id).first()
    if library is None:
        raise HTTPException(404, detail="Library not found")
    results = []
    for key, title, chapters in DEMO_STORIES:
        url = f"nexus-demo:{key}"
        novel = db.query(Novel).filter_by(library_id=library.id, url=url).first()
        created = novel is None
        if created:
            novel = Novel(library_id=library.id, title=title, author="Nexus demo", url=url,
                novel_site="local", site="local", scrape_status="completed", status="completed",
                chapter_count=len(chapters), num_chapters=len(chapters),
                description="An original Nexus demo story. Public-domain fixture (CC0).")
            db.add(novel); db.flush()
            for number, (heading, html) in enumerate(chapters, 1):
                document = from_html(html)
                db.add(Chapter(novel_id=novel.id, chapter_number=number, title=heading,
                    document=document, content=document["plain_text"], content_status=ContentStatus.PRESENT,
                    word_count=len(document["plain_text"].split())))
        results.append(DemoStory(novel_id=novel.id, title=novel.title, created=created))
    db.commit()
    return DemoResponse(library_id=library.id, stories=results)
