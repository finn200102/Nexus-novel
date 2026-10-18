"""Retained source provenance survives changing the active download source."""
# ruff: noqa: F811
from types import SimpleNamespace
import pytest
from app.models import Novel
from app.services import processing_permissions
from tests.routes.conftest import db,test_user,test_library  # noqa: F401


def test_retained_ao3_original_still_requires_separate_external_permission(db,test_user,test_library):
    novel=Novel(library_id=test_library.id,title='Reviewed new source',site='royalroad',novel_site='royalroad',
        url='https://www.royalroad.com/fiction/9',source_url='https://www.royalroad.com/fiction/9')
    db.add(novel);db.commit()
    assert not processing_permissions.is_ao3(novel)
    novel.manifest_state.ao3_material=True
    db.commit();db.expire_all()
    assert processing_permissions.is_ao3(novel)
    remote=SimpleNamespace(id=999,kind='openai')
    with pytest.raises(PermissionError,match='AO3 material'):
        processing_permissions.check(db,test_user.id,novel,remote,'companion',consent=True)
    processing_permissions.check(db,test_user.id,novel,remote,'companion',consent=True,ao3_consent=True)
    processing_permissions.check(db,test_user.id,novel,SimpleNamespace(kind='local'),'companion')
