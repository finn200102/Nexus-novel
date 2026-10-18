import asyncio

from fastapi import APIRouter, Depends, Query, Response, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional
from app.auth.dependencies import get_current_user, get_current_auth, Authenticated
from config.database import get_db
from app.models.novel import Novel
from app.models.user import User
from app.services import metadata_client
from app.services.content_limit_service import ensure_story_allowed
from app.services.blocklist_service import apply_blocklist, merged_exclusions
from app.services.library_organization_service import personal_for_novels
from app.services.recommendation_reasons import ReasonSource, build_reasons, terms_of
from app.schemas.catalog_discovery import GroupedWorkPage
from app.services import catalog_read_service
from app.services import progressive_search_service as progressive
from app.schemas.live_search import LiveCapabilitiesResponse, LiveSearchPage, LiveSourcePage

router = APIRouter(
    prefix="/discovery",
    tags=["discovery"],
    responses={404: {"description": "Not found"}},
)


def _reader_novel(
    db: Session,
    *,
    current_user: User,
    metadata_novel_id: int,
) -> Novel | None:
    """Return this user's copy of a metadata work, never another user's copy."""
    return (
        db.query(Novel)
        .join(Novel.library)
        .filter(Novel.metadata_id == metadata_novel_id)
        .filter(Novel.library.has(user_id=current_user.id))
        .order_by(Novel.id.asc())
        .first()
    )


def _scoped_portrait_urls(value,novel_id):
    """Upstream scoped responses contain provenanced portraits only.

    URLs are API-relative; clients fetch through their authenticated API base.
    Never proxy an arbitrary upstream URL or trust URL query as authorization.
    """
    from urllib.parse import quote
    if isinstance(value,list):
        return [_scoped_portrait_urls(item,novel_id) for item in value]
    if not isinstance(value,dict):return value
    result={key:_scoped_portrait_urls(item,novel_id) for key,item in value.items()}
    portrait=result.get('portrait')
    if isinstance(portrait,dict):
        artifact_id=portrait.get('id')
        if isinstance(artifact_id,str) and artifact_id and len(artifact_id)<=200:
            portrait['url']=f'/discovery/story-guide/media/{quote(artifact_id,safe="")}?novel_id={novel_id}'
        else:result.pop('portrait',None)
    return result


async def _reader_guide(db,user,novel_id,operation,response,requested=None,args=None):
    from app.services.reader_story_scope_service import request_snapshot,empty_response
    from starlette.concurrency import run_in_threadpool
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    if operation in {'regenerate','portrait'}:
        raise HTTPException(403,detail={'code':'reader_provider_required','message':'Story Guide generation requires a private provider workflow with explicit story permission and a spending budget. Use the configured private companion while provider-aware guide generation is being completed.'})
    user_id=user.id
    proof,local,run_key=await run_in_threadpool(request_snapshot,db,user_id,novel_id,requested)
    args=dict(args or {})
    if proof['through_chapter'] is None:
        result=empty_response(operation,novel_id,args)
    else:
        cutoff=proof['through_chapter']
        if operation=='changes':args['from_chapter']=min(args.get('from_chapter',cutoff),cutoff)
        if operation=='dossier' and args['chapter_number'] not in {chapter['chapter_number'] for chapter in proof['chapters']}:
            return empty_response(operation,novel_id,args)
        result=await metadata_client.reader_story_guide(novel_id,operation=operation,scope=proof,args=args)
        current=await run_in_threadpool(request_snapshot,db,user_id,novel_id,requested)
        if current!=(proof,local,run_key):
            raise HTTPException(409,detail={'code':'reading_scope_changed','message':'Your verified reading changed while the guide was loading. Reopen the guide for the current reading.'})
    if operation!='media':result=_scoped_portrait_urls(result,novel_id)
    if operation=='projection' and local is not None:
        result['reader_context']=local
    return result


@router.get("/novels/")
@router.get("/works", response_model=GroupedWorkPage)
async def get_novels(
    request: Request,
    q: Optional[str] = Query(None, max_length=500),
    site: Optional[str] = Query(
        None,
        description="Filter by site: royalroad, fanfiction, webnovel, archive, spacebattles, sufficientvelocity, questionablequesting, scribblehub",
    ),
    author: Optional[str] = Query(None, description="Filter by author name"),
    title: Optional[str] = Query(None, description="Search by title"),
    tag: Optional[list[str]] = Query(None, description="Source tag contains (repeatable)"),
    tag_mode: str = Query("all", pattern="^(all|any)$", description="all or any for repeated tag, fandom and genre values"),
    fandom: Optional[list[str]] = Query(None, description="Fandom contains (repeatable)"),
    genre: Optional[list[str]] = Query(None, description="Source genre contains (repeatable)"),
    exclude_tag: Optional[list[str]] = Query(None, description="Hide exact source tag (repeatable)"),
    exclude_fandom: Optional[list[str]] = Query(None, description="Hide exact fandom (repeatable)"),
    exclude_genre: Optional[list[str]] = Query(None, description="Hide exact genre (repeatable)"),
    exclude_author: Optional[list[str]] = Query(None, description="Hide exact author name (repeatable)"),
    exclude_text: Optional[list[str]] = Query(None, description="Hide works whose title or summary contains this (repeatable)"),
    language: Optional[list[str]] = Query(None, description="Detected language (repeatable)"),
    complete_only: bool = Query(False, description="Only completed works"),
    hide_inactive: bool = Query(False, description="Hide works that have stopped updating"),
    crossover: Optional[bool] = Query(None, description="true for multi-fandom works, false for single-fandom"),
    status: Optional[str] = Query(None, description="Filter by publication status"),
    min_word_count: Optional[int] = Query(None, ge=0),
    min_favorites: Optional[int] = Query(None, ge=0),
    min_follows: Optional[int] = Query(None, ge=0),
    min_reviews: Optional[int] = Query(None, ge=0),
    min_chapter_count: Optional[int] = Query(None, ge=0),
    max_word_count: Optional[int] = Query(None, ge=0),
    updated_since_days: Optional[int] = Query(None, ge=1, le=3650),
    label: Optional[str] = Query(None),
    label_origin: Optional[str] = Query(None, pattern="^(source|ai|user|community)$"),
    import_state: Optional[str] = Query(None, pattern="^(ready|in_progress)$"),
    similar_to: Optional[int] = Query(None, ge=1, description="Return works similar to this Nexus work"),
    canonical_include: Optional[list[str]] = Query(None, max_length=100),
    canonical_exclude: Optional[list[str]] = Query(None, max_length=100),
    sort_by: str = Query("updated"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
    cursor: Optional[int] = Query(None, description="Pagination cursor"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    auth: Authenticated = Depends(get_current_auth),
):
    """Get novels from metadata server with optional filtering.

    The user's blocklist is merged into the exclude_* parameters, and blocked
    rows are dropped again from the page the server returned.
    """
    blocked = merged_exclusions(
        db,
        current_user,
        exclude_tag=exclude_tag,
        exclude_fandom=exclude_fandom,
        exclude_genre=exclude_genre,
        exclude_author=exclude_author,
        exclude_text=exclude_text,
    )
    from app.services.catalog_watch_service import fingerprint
    account_key = current_user.storage_id
    user_id = current_user.id
    session_id = auth.session.id
    visibility_key = fingerprint(merged_exclusions(db, current_user))
    seed_visibility = merged_exclusions(db, current_user)
    db.commit()
    grouped = request.url.path.rstrip('/').endswith('/works')
    data = await catalog_read_service.list_novels(
        q=q,
        site=site,
        author=author,
        title=title,
        tag=tag,
        tag_mode=tag_mode,
        fandom=fandom,
        genre=genre,
        exclude_tag=blocked["exclude_tag"],
        exclude_fandom=blocked["exclude_fandom"],
        exclude_genre=blocked["exclude_genre"],
        exclude_author=blocked["exclude_author"],
        exclude_text=blocked["exclude_text"],
        language=language,
        complete_only=complete_only,
        hide_inactive=hide_inactive,
        crossover=crossover,
        status=status,
        min_word_count=min_word_count,
        min_favorites=min_favorites,
        min_follows=min_follows,
        min_reviews=min_reviews,
        min_chapter_count=min_chapter_count,
        max_word_count=max_word_count,
        updated_since_days=updated_since_days,
        label=label,
        label_origin=label_origin,
        import_state=import_state,
        similar_to=similar_to,
        canonical_include=canonical_include,
        canonical_exclude=canonical_exclude,
        grouped=grouped,
        seed_visibility=seed_visibility if similar_to is not None else None,
        content_rating=blocked["content_rating"],
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        cursor=cursor,
    )
    db.expire_all()
    current_user = db.get(User, user_id)
    from app.models.account import UserSession
    session=db.get(UserSession,session_id)
    if session is None or session.revoked_at is not None or session.user_id!=user_id:
        raise HTTPException(401,detail='Session ended. Sign in again.')
    if current_user is None or current_user.is_disabled or current_user.storage_id != account_key:
        raise HTTPException(403, detail='Account is unavailable')
    if fingerprint(merged_exclusions(db, current_user)) != visibility_key:
        raise HTTPException(409, detail={'code':'catalog_visibility_changed','message':'Your content rules changed. Search again.'})
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        if grouped:
            groups = []
            for group in data['data']:
                members = apply_blocklist(db, current_user, group.get('editions', []))
                # Metadata must filter before grouping/counting. A mismatch is
                # rejected rather than exposing a hidden group's title/count.
                if len(members) != len(group.get('editions', [])) or not members:
                    raise HTTPException(409, detail={'code':'catalog_visibility_changed','message':'Catalog visibility changed. Search again.'})
                groups.append({**group, 'title':members[0]['title'], 'representative':members[0],
                    'editions':members, 'matching_edition_count':len(members)})
            data = {**data, 'data':groups}
        else:
            data = {**data, "data": apply_blocklist(db, current_user, data["data"])}
    db.commit()
    return data


@router.get("/novels/{novel_id}")
async def get_novel_by_id(
    novel_id: int,
    current_user: User = Depends(get_current_user),
):
    """Get a single novel's details from metadata server.

    403 when the story is outside the user's content limits.
    """
    data = await metadata_client.get_novel_metadata(novel_id)
    await ensure_story_allowed(current_user, novel_id)
    return data


async def _reader_analysis_request(db, auth, novel_id, *, enqueue=False):
    from app.routers.catalog_editions import snapshot
    from app.services.content_limit_service import item_allowed, restricted
    from starlette.concurrency import run_in_threadpool

    user_id, session_id = auth.user.id, auth.session.id
    proof = await run_in_threadpool(snapshot, db, user_id, session_id)
    metadata = await _safe_metadata(novel_id)
    if await run_in_threadpool(snapshot, db, user_id, session_id) != proof:
        raise HTTPException(409, detail={'code':'catalog_visibility_changed',
            'message':'Your content rules changed. Reopen this story.'})
    user = db.get(User, user_id)
    try:
        if metadata is None:
            raise HTTPException(404, detail='Story is unavailable')
        if not item_allowed(user, metadata):
            raise restricted()
        if not apply_blocklist(db, user, [metadata]):
            raise HTTPException(404, detail='Story is unavailable')
    finally:
        # Close the user transaction before waiting on the metadata service.
        db.commit()
    operation = metadata_client.enqueue_novel_analysis if enqueue else metadata_client.get_novel_analysis
    try:
        result = await operation(novel_id, seed_visibility=proof[2])
    except (RuntimeError, ValueError, TypeError) as exc:
        catalog_read_service.unavailable(exc)
    if await run_in_threadpool(snapshot, db, user_id, session_id) != proof:
        raise HTTPException(409, detail={'code':'catalog_visibility_changed',
            'message':'Your content rules changed. Reopen this story.'})
    return result


@router.get("/novels/{novel_id}/analysis")
async def get_novel_analysis(novel_id: int, response: Response,
    db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return await _reader_analysis_request(db, auth, novel_id)


@router.post("/novels/{novel_id}/analysis/enqueue")
async def enqueue_novel_analysis(novel_id: int, response: Response,
    db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    """Queue local enrichment only after the reader's story visibility check."""
    response.headers['Cache-Control']='private, no-store'
    return await _reader_analysis_request(db, auth, novel_id, enqueue=True)


@router.get("/novels/{novel_id}/similar")
async def get_similar_novels(
    novel_id: int,
    limit: int = Query(8, ge=1, le=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    auth: Authenticated = Depends(get_current_auth),
):
    """Similar works with a "why this" reason list for each row."""
    from app.routers.catalog_editions import snapshot
    from starlette.concurrency import run_in_threadpool
    user_id=current_user.id
    session_id=auth.session.id
    proof=await run_in_threadpool(snapshot,db,user_id,session_id)
    source_metadata=await _safe_metadata(novel_id)
    if await run_in_threadpool(snapshot,db,user_id,session_id) != proof:
        raise HTTPException(409,'Your content rules changed. Search again.')
    current_user=db.get(User,user_id)
    from app.services.content_limit_service import item_allowed, restricted
    if source_metadata is not None and not item_allowed(current_user,source_metadata):
        raise restricted()
    if source_metadata is None or not apply_blocklist(db,current_user,[source_metadata]):
        raise HTTPException(404,'Story is unavailable')
    db.commit()
    data = await metadata_client.get_similar_novels(novel_id, limit, seed_visibility=proof[2])
    result_key='results' if isinstance(data,dict) and 'results' in data else 'data'
    rows = data.get(result_key, []) if isinstance(data, dict) else list(data or [])
    if not rows:
        if await run_in_threadpool(snapshot,db,user_id,session_id) != proof:
            raise HTTPException(409,'Your content rules changed. Search again.')
        return data

    candidates = await asyncio.gather(*(_safe_metadata(int(row["novel_id"])) for row in rows if row.get("novel_id")))
    candidate_by_id = {int(row["novel_id"]): meta for row, meta in zip([r for r in rows if r.get("novel_id")], candidates)}
    if await run_in_threadpool(snapshot,db,user_id,session_id) != proof:
        raise HTTPException(409,'Your content rules changed. Search again.')
    current_user=db.get(User,user_id)
    source = _reason_source(db, current_user, novel_id, source_metadata)
    enriched = []
    for row in rows:
        metadata = candidate_by_id.get(int(row["novel_id"])) if row.get("novel_id") else None
        if metadata is None or not apply_blocklist(db,current_user,[metadata]):
            continue
        merged = {**(metadata or {}), **row}
        merged["reasons"] = build_reasons(merged, [source]) if source else []
        enriched.append(merged)
    blocked_filtered = apply_blocklist(db, current_user, enriched)
    if isinstance(data, dict):
        return {**data, result_key: blocked_filtered}
    return blocked_filtered


async def _safe_metadata(novel_id: int) -> dict | None:
    try:
        return await metadata_client.get_novel_metadata(novel_id)
    except Exception:
        return None


def _reason_source(db: Session, current_user: User, novel_id: int, metadata: dict | None) -> ReasonSource | None:
    if not metadata:
        return None
    local = _reader_novel(db, current_user=current_user, metadata_novel_id=novel_id)
    rating = None
    if local is not None:
        rating = personal_for_novels(db, current_user, [local.id]).get(local.id, {}).get("rating")
    return ReasonSource(
        title=metadata.get("title") or "this story",
        terms=terms_of(metadata),
        author=metadata.get("author"),
        rating=rating,
    )


# Signed chapter numbers are labels, and None means no verified evidence.
SIGNED_MIN=-2147483648
SIGNED_MAX=2147483647


@router.get('/novels/{novel_id}/story-guide')
async def get_story_guide(novel_id:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'guide',response,through_chapter)


@router.get('/novels/{novel_id}/story-guide/entities')
async def get_story_guide_entities(novel_id:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'entities',response,through_chapter)


@router.get('/novels/{novel_id}/story-guide/relationships')
async def get_story_guide_relationships(novel_id:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'relationships',response,through_chapter)


@router.get('/novels/{novel_id}/story-guide/projection')
async def get_story_guide_projection(novel_id:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'projection',response,through_chapter)


@router.get('/novels/{novel_id}/story-guide/changes')
async def get_story_guide_changes(novel_id:int,response:Response,from_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'changes',response,through_chapter,{} if from_chapter is None else {'from_chapter':from_chapter})


@router.get('/novels/{novel_id}/story-guide/entities/{entity_id}/profile')
async def get_story_guide_entity_profile(novel_id:int,entity_id:str,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'profile',response,through_chapter,{'entity_id':entity_id})


@router.get('/novels/{novel_id}/story-guide/relationships/timeline')
async def get_story_guide_relationship_timeline(novel_id:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),entity_id:str|None=Query(None,max_length=200),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'timeline',response,through_chapter,{} if entity_id is None else {'entity_id':entity_id})


@router.get('/novels/{novel_id}/story-guide/chapters/{chapter_number}')
async def get_story_guide_chapter_dossier(novel_id:int,chapter_number:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'dossier',response,through_chapter,{'chapter_number':chapter_number})


@router.get('/novels/{novel_id}/story-guide/entities/{entity_id}')
async def get_story_guide_entity_article(novel_id:int,entity_id:str,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'article',response,through_chapter,{'entity_id':entity_id})


@router.post('/novels/{novel_id}/story-guide/backfill')
async def backfill_story_guide(novel_id:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'backfill',response,through_chapter)


@router.post('/novels/{novel_id}/story-guide/regenerate')
async def regenerate_story_guide(novel_id:int,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'regenerate',response,through_chapter)


@router.post('/novels/{novel_id}/story-guide/characters/portrait')
async def create_story_guide_portrait(novel_id:int,payload:dict,response:Response,through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    return await _reader_guide(db,current_user,novel_id,'portrait',response,through_chapter,{'payload':payload})


@router.get('/story-guide/media/{artifact_id}')
async def get_story_guide_media(artifact_id:str,response:Response,novel_id:int=Query(gt=0),through_chapter:int|None=Query(None,ge=SIGNED_MIN,le=SIGNED_MAX),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    content,media_type=await _reader_guide(db,current_user,novel_id,'media',response,through_chapter,{'artifact_id':artifact_id})
    return Response(content,media_type=media_type,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get("/novels/{novel_id}/editions")
async def get_novel_editions(novel_id: int, response: Response,
    db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    from app.routers.catalog_editions import editions
    group = await editions(novel_id=novel_id, response=response, db=db, auth=auth)
    return {'id':group['canonical_work_id'], 'title':group['title'],
        'editions':[{'id':member['edition_id'], 'novel_id':member['novel_id'],
            'edition_kind':member['edition_kind'], 'language':member['language'],
            **{key:member[key] for key in ('created_at','updated_at') if member.get(key) is not None}}
            for member in group['editions']]}


@router.get("/sites/")
async def get_supported_sites(
    current_user: User = Depends(get_current_user),
):
    """Get list of supported sites."""
    return {
        "sites": [
            {"id": "royalroad", "name": "Royal Road"},
            {"id": "fanfiction", "name": "FanFiction.Net"},
            {"id": "spacebattles", "name": "SpaceBattles"},
            {"id": "archive", "name": "Archive of Our Own"},
            {"id": "webnovel", "name": "WebNovel"},
            {"id": "sufficientvelocity", "name": "Sufficient Velocity"},
            {"id": "questionablequesting", "name": "Questionable Questing"},
            {"id": "scribblehub", "name": "ScribbleHub"},
        ]
    }


@router.get("/fandoms/")
async def get_fandoms(
    site: Optional[str] = Query(None, description="Restrict to a source site"),
    media_type: Optional[str] = Query(None, description="Restrict to a source archive category"),
    q: Optional[str] = Query(None, description="Search canonical fandom names"),
    limit: int = Query(100, ge=1, le=250),
    current_user: User = Depends(get_current_user),
):
    """Expose persisted source fandoms without making the browser call metadata directly."""
    return await metadata_client.list_fandoms_metadata(
        site=site, media_type=media_type, query=q, limit=limit
    )


# --- Live site search (WP-4) -------------------------------------------------
# Sites with a working keyword search on the metadata server.
LIVE_SEARCH_SITES = (
    "royalroad",
    "fanfiction",
    "archive",
    "spacebattles",
    "sufficientvelocity",
    "questionablequesting",
    "webnovel",
)


def _url_key(url: str | None) -> str:
    if not url:
        return ""
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url.strip())
    return urlunsplit(('https' if parts.scheme in {'http', 'https'} else parts.scheme,
                      parts.netloc.lower(), parts.path.rstrip('/'), parts.query, ''))


def _local_hit(row: dict) -> dict:
    return {
        **row,
        "metadata_id": row.get("id"),
        "url": row.get("source_url"),
        "sources": ["local"],
    }


@router.get("/live/capabilities", response_model=LiveCapabilitiesResponse)
async def live_capabilities(response: Response, db: Session = Depends(get_db),
                            auth: Authenticated = Depends(get_current_auth)):
    response.headers['Cache-Control'] = 'private, no-store'
    context = await progressive.begin(db, auth)
    return await progressive.capabilities(db, context)


@router.get('/live/local', response_model=LiveSearchPage)
async def live_local(response: Response, q: str = Query(..., min_length=1, max_length=200),
                     page: int = Query(1, ge=1, le=50), limit: int = Query(20, ge=1, le=100),
                     db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    response.headers['Cache-Control'] = 'private, no-store'
    progressive.query(q)
    context = await progressive.begin(db, auth)
    return await progressive.local(db, context, q, page, limit)


@router.get('/live/source', response_model=LiveSourcePage)
async def live_source(response: Response,
                      source_id: str = Query(..., max_length=80, pattern=r'^[a-z][a-z0-9_-]*$'),
                      q: str = Query(..., min_length=1, max_length=200),
                      page: int = Query(1, ge=1, le=50),
                      pinned_digest: str | None = Query(None, pattern=r'^[0-9a-f]{64}$'),
                      db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    response.headers['Cache-Control'] = 'private, no-store'
    progressive.query(q)
    context = await progressive.begin(db, auth)
    return await progressive.source(db, context, source_id, q, page, pinned_digest)


@router.get("/live")
async def live_search(
    response: Response,
    q: str = Query(..., min_length=1, max_length=200),
    sites: Optional[list[str]] = Query(None, max_length=100, description="Capability source IDs (repeatable)"),
    page: int = Query(1, ge=1, le=50),
    include_local: bool = Query(True),
    db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth),
):
    """Legacy aggregate; new clients independently request local/source pages."""
    response.headers['Cache-Control'] = 'private, no-store'
    q = progressive.query(q)
    context = await progressive.begin(db, auth)
    available = await progressive.capabilities(db, context)
    searchable = {item.source_id: item for item in available.sources if item.search}
    chosen = list(dict.fromkeys(sites if sites is not None else searchable))
    if not chosen or len(chosen) > 16 or any(site not in searchable for site in chosen):
        raise HTTPException(422, detail='Choose 1–16 available searchable sources')
    local_rows = []
    if include_local and page == 1:
        # Retained legacy title-search semantics; the new local endpoint offers
        # full lexical catalog ranking with visibility applied before paging.
        try:
            local = await metadata_client.list_novels_metadata(title=q, limit=20, **context[2][2])
            local_rows = local.get('data', []) if isinstance(local, dict) else []
        except RuntimeError:
            local_rows = []
        await progressive.checked(db, context)
    semaphore = asyncio.Semaphore(3)
    async def request_source(site):
        params = {'site': site, 'q': q, 'page': page}
        if searchable[site].digest:
            params['pinned_digest'] = searchable[site].digest
        async with semaphore:
            return await metadata_client.live_listing('live', params)
    answers = await asyncio.gather(*(request_source(site) for site in chosen))
    merged = {}
    for row in progressive.valid_rows([_local_hit(row) for row in local_rows]):
        key = _url_key(row.get('source_url')) or f"local:{row.get('id')}"
        merged[key] = row
    errors = []
    for site, answer in zip(chosen, answers):
        result = await progressive.page_from_answer(db, context, site, page, answer)
        errors.extend(result['errors'])
        for item in result['results']:
            key = _url_key(item.get('source_url')) or f"live:{site}:{item.get('id')}"
            if key in merged:
                merged[key]['sources'] = sorted({*merged[key]['sources'], 'live'})
            else:
                merged[key] = item
    return {'query': q, 'page': page, 'sites': chosen,
            'results': await progressive.checked(db, context, list(merged.values())), 'errors': errors}


@router.get('/live/browse', response_model=LiveSourcePage)
async def live_browse(response: Response,
    site: str | None = Query(None, max_length=80, pattern=r'^[a-z][a-z0-9_-]*$'),
    source_id: str | None = Query(None, max_length=80, pattern=r'^[a-z][a-z0-9_-]*$'),
    feed: str = Query(..., min_length=1, max_length=200),
    page: int = Query(1, ge=1, le=50),
    pinned_digest: str | None = Query(None, pattern=r'^[0-9a-f]{64}$'),
    db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth),
):
    response.headers['Cache-Control'] = 'private, no-store'
    if not (source_id or site) or (source_id and site and source_id != site):
        raise HTTPException(422, detail='Choose one source')
    context = await progressive.begin(db, auth)
    result = await progressive.source(db, context, source_id or site, '', page, pinned_digest, feed=feed)
    return {**result, 'site': source_id or site, 'feed': feed}
