from unittest.mock import AsyncMock

import pytest

from app.models import Novel
from app.schemas.novel import Novel as NovelResponse
from app.services import metadata_client


@pytest.mark.parametrize('rating', [4.83, 4, None])
def test_source_rating_roundtrips_without_losing_fraction(db, test_library, rating):
    novel = Novel(title='Rated story', url='https://www.royalroad.com/fiction/81',
        library_id=test_library.id, rating=rating)
    db.add(novel)
    db.commit()
    db.refresh(novel)
    assert NovelResponse.model_validate(novel).rating == rating


def test_library_and_story_endpoints_accept_fractional_source_rating(client, auth_headers, db, test_library, monkeypatch):
    novel = Novel(title='Rated story', url='https://www.royalroad.com/fiction/81',
        library_id=test_library.id, rating=4.83, metadata_id=81, scrape_status='completed')
    db.add(novel)
    db.commit()
    monkeypatch.setattr(metadata_client, 'get_novel_metadata', AsyncMock(return_value={}))
    listing = client.get(f'/novel/?library_id={test_library.id}', headers=auth_headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()[0]['rating'] == 4.83
    detail = client.get(f'/novel/{novel.id}?library_id={test_library.id}', headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()['rating'] == 4.83
