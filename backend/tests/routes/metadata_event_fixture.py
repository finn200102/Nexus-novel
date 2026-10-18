"""A complete immutable peer snapshot, independent of event numeric hints."""
from copy import deepcopy
from hashlib import sha256
import json
from uuid import NAMESPACE_URL,uuid5
from app.models import Chapter
from app.models.chapter_manifest import ChapterManifestState
from app.services import metadata_client


def peer(db,novel,monkeypatch,added):
    state=db.get(ChapterManifestState,novel.id)
    source=state.metadata_source or dict(site=novel.novel_site,story_id=novel.story_id or novel.site_story_id or novel.metadata_id,
        source_url=novel.source_url or novel.url)
    # These legacy fixtures predate stored source IDs; declare their original
    # source in setup, never derive identity from an incoming event number.
    if novel.story_id is None:novel.story_id=source['story_id']
    if novel.site_story_id is None:novel.site_story_id=source['story_id']
    if novel.source_url is None:novel.source_url=source['source_url']
    assert source['source_url']==(novel.source_url or novel.url)
    assert source['site'] in (novel.site,novel.novel_site)
    assert source['story_id'] in (novel.story_id,novel.site_story_id)
    namespace=state.metadata_manifest_key or str(uuid5(NAMESPACE_URL,f'webhook-peer-work:{novel.metadata_id}'))
    records={}
    for row in db.query(Chapter).filter_by(novel_id=novel.id).order_by(Chapter.chapter_number):
        external=row.site_chapter_id
        records[row.chapter_number]=dict(chapter_number=row.chapter_number,chapter_id=external,title=row.title,url=row.source_url,
            category=row.category,word_count=row.word_count,chapter_key=row.metadata_chapter_key or str(uuid5(NAMESPACE_URL,f'{namespace}:{external}')))
    for row in added:
        number=row['chapter_number']
        value={**records.get(number,{}),**row}
        value.setdefault('chapter_id',100+number);value.setdefault('title',f'Chapter {number}')
        value.setdefault('url',f'https://synthetic.invalid/chapter/{value["chapter_id"]}')
        value.setdefault('category','story');value.setdefault('word_count',100)
        value.setdefault('chapter_key',str(uuid5(NAMESPACE_URL,f'{namespace}:{value["chapter_id"]}')))
        records[number]=value
    items=[dict(id=index,site=source['site'],story_id=source['story_id'],identity_kind='stable_source_id',**value)
        for index,value in enumerate(sorted(records.values(),key=lambda value:value['chapter_number']),1)]
    canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    header=dict(protocol=1,novel_id=novel.metadata_id,manifest_key=namespace,source=source,identity_kind='stable_source_id',total=len(items))
    packed=canonical(header)+b'\n'+b''.join(canonical(item)+b'\n' for item in items)
    snapshot=metadata_client.ChapterManifestSnapshot(novel_id=novel.metadata_id,manifest_key=namespace,source=source,
        revision=sha256(b'revision:'+packed).hexdigest(),fingerprint=sha256(packed).hexdigest(),identity_kind='stable_source_id',total=len(items),items=items)
    metadata_id=novel.metadata_id
    async def capabilities(*args,**kwargs):
        assert not db.in_transaction()
        return {'protocols':[1],'content_identity':True}
    async def manifest(selected,**kwargs):
        assert selected==metadata_id and kwargs.get('force_refresh') is True and not db.in_transaction()
        return deepcopy(snapshot)
    monkeypatch.setattr(metadata_client,'_manifest_request',capabilities)
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',manifest)
    db.commit()
    selected={row['chapter_number'] for row in added}
    proof=dict(protocol=1,manifest_key=namespace,revision=snapshot.revision,fingerprint=snapshot.fingerprint,source=source,
        chapters=[dict(chapter_key=row['chapter_key'],chapter_number=row['chapter_number']) for row in items if row['chapter_number'] in selected])
    return snapshot,proof
