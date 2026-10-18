"""Continue labels do not follow a reused database address."""
# ruff: noqa: F811
from sqlalchemy import delete
from app.models import Chapter
from app.services import chapter_reading_service as service
from tests.routes.test_chapter_reading_summary import indexed  # noqa: F401
from tests.routes.conftest import db,test_user,test_library  # noqa: F401


def test_reused_current_fk_does_not_make_replacement_the_current_chapter(db,test_user,indexed):
    novel,chapters,_,point=indexed
    chapter=chapters[3]
    identifier,old_key=chapter.id,chapter.chapter_key
    db.expunge(chapter)
    db.execute(delete(Chapter).where(Chapter.id==identifier).execution_options(synchronize_session=False));db.commit()
    replacement=Chapter(id=identifier,novel_id=novel.id,chapter_number=7,title='Replacement')
    db.add(replacement);db.commit()
    assert replacement.chapter_key!=old_key
    current=service.summary(db,test_user.id,novel.id)['current']
    assert current['chapter_id'] is None and current['ordinal'] is None and current['followed_ordinal'] is None
    assert current['chapter_number']==point.chapter_number
