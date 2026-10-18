"""SQL-only private views: no catalog enrichment, fetching, or chapter bodies."""
from fastapi import HTTPException
from sqlalchemy import case,func,or_,and_
from app.models import Novel,Library,Chapter,ReadingProgress
from app.models.follow import UserNovelFollow
from app.models.novel_personal import NovelPersonalData,NovelUserTag
from app.models.shelf import Shelf,ShelfNovel
from app.schemas.library_views import OwnedLibraryDefinition,LibraryStoryItem,SOURCE_ALIASES,SOURCES
from app.services.source_status_service import SITE_LABELS

STATES=('plan_to_read','reading','on_hold','completed','dropped','ignored')
HOSTS={'archive':'archiveofourown.org','fanfiction':'fanfiction.net','royalroad':'royalroad.com','scribblehub':'scribblehub.com','webnovel':'webnovel.com','spacebattles':'forums.spacebattles.com','sufficientvelocity':'forums.sufficientvelocity.com','questionablequesting':'forum.questionablequesting.com'}


def validate_definition(db,user_id,definition):
    if not isinstance(definition,OwnedLibraryDefinition):definition=OwnedLibraryDefinition.model_validate(definition)
    if definition.library_ids:
        found={row[0] for row in db.query(Library.id).filter(Library.user_id==user_id,Library.id.in_(definition.library_ids)).all()}
        if found!=set(definition.library_ids):raise HTTPException(404,'Library not found')
    if definition.shelf_id is not None and db.query(Shelf.id).filter_by(id=definition.shelf_id,user_id=user_id).first() is None:
        raise HTTPException(404,'Shelf not found')
    return definition


def source_expression():
    site=func.lower(func.coalesce(func.nullif(func.trim(Novel.novel_site),''),func.nullif(func.trim(Novel.site),''),''))
    aliases={name:name for name in SOURCES};aliases.update(SOURCE_ALIASES)
    by_site=[(site.in_([alias for alias,target in aliases.items() if target==name]),name) for name in sorted(SOURCES)]
    by_url=[]
    for name,host in HOSTS.items():
        matches=[]
        for field in (Novel.source_url,Novel.url):
            for scheme in ('http://','https://'):
                for www in ('','www.'):
                    prefix=scheme+www+host
                    matches.extend((func.lower(field)==prefix,func.lower(field).like(prefix+'/%')))
        by_url.append((or_(*matches),name))
    return case(*by_site,(Novel.url.like('nexus-local:epub:%'),'local'),*by_url,else_=None)


def follow_expression():
    return case((UserNovelFollow.state.in_(STATES),UserNovelFollow.state),(Novel.follow_state.in_(STATES),Novel.follow_state),else_='plan_to_read')


def base_query(db,user_id,definition):
    query=db.query(Novel).join(Library,Library.id==Novel.library_id).filter(Library.user_id==user_id)
    if definition.library_ids:query=query.filter(Novel.library_id.in_(definition.library_ids))
    return query


def filtered_query(db,user_id,definition):
    query=base_query(db,user_id,definition).outerjoin(UserNovelFollow,and_(UserNovelFollow.novel_id==Novel.id,UserNovelFollow.user_id==user_id)).outerjoin(
        NovelPersonalData,and_(NovelPersonalData.novel_id==Novel.id,NovelPersonalData.user_id==user_id))
    if definition.q:
        pattern='%'+definition.q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        query=query.filter(or_(Novel.title.ilike(pattern,escape='\\'),Novel.author.ilike(pattern,escape='\\')))
    if definition.source:query=query.filter(source_expression()==definition.source)
    if definition.user_tag:
        query=query.filter(db.query(NovelUserTag.id).filter(NovelUserTag.novel_id==Novel.id,NovelUserTag.user_id==user_id,NovelUserTag.tag==definition.user_tag).exists())
    if definition.min_rating is not None:query=query.filter(NovelPersonalData.rating>=definition.min_rating)
    if definition.shelf_id is not None:
        query=query.filter(db.query(ShelfNovel.id).join(Shelf,Shelf.id==ShelfNovel.shelf_id).filter(ShelfNovel.novel_id==Novel.id,ShelfNovel.shelf_id==definition.shelf_id,Shelf.user_id==user_id).exists())
    return query


def page(db,user_id,definition,offset=0,limit=50):
    definition=validate_definition(db,user_id,definition)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise HTTPException(422,'Choose a valid library page')
    query=filtered_query(db,user_id,definition);state=follow_expression()
    counts=dict(query.with_entities(state,func.count(Novel.id)).group_by(state).all())
    if definition.follow_states:query=query.filter(state.in_(definition.follow_states))
    total=query.count();library_total=base_query(db,user_id,definition).count()
    title=func.lower(Novel.title)
    updated=func.coalesce(Novel.updated_date,Novel.publish_date,Novel.updated_at,Novel.created_at)
    actual_max=db.query(func.max(Chapter.chapter_number)).filter(Chapter.novel_id==Novel.id).correlate(Novel).scalar_subquery()
    actual_count=db.query(func.count(Chapter.id)).filter(Chapter.novel_id==Novel.id).correlate(Novel).scalar_subquery()
    chapter_count=func.coalesce(Novel.chapter_count,Novel.num_chapters,actual_count,0)
    if definition.sort_by=='title':order=(title.asc(),Novel.id.asc())
    elif definition.sort_by=='chapters':order=(chapter_count.desc(),title.asc(),Novel.id.asc())
    elif definition.sort_by=='personal_rating':order=(case((NovelPersonalData.rating.is_(None),1),else_=0),NovelPersonalData.rating.desc(),title.asc(),Novel.id.asc())
    elif definition.sort_by=='updated_since_read':
        query=query.outerjoin(ReadingProgress,and_(ReadingProgress.user_id==user_id,ReadingProgress.novel_id==Novel.id))
        # A chapter count is a cardinality, never a signed source label.
        # The (0,0) furthest sentinel is not a visited chapter.
        furthest_known=and_(ReadingProgress.furthest_chapter_number.isnot(None),or_(ReadingProgress.furthest_chapter_number!=0,ReadingProgress.furthest_percent>0))
        visited=case((furthest_known,ReadingProgress.furthest_chapter_number),else_=ReadingProgress.chapter_number)
        newer=and_(visited.isnot(None),actual_max.isnot(None),actual_max>visited)
        order=(case((newer,1),else_=0).desc(),updated.desc(),title.asc(),Novel.id.asc())
    else:order=(updated.desc(),Novel.id.desc())
    # Project only the public story DTO fields, never relationships or bodies.
    names=[key for key in LibraryStoryItem.model_fields if hasattr(Novel,key) and key!='follow_state']
    rows=query.with_entities(*[getattr(Novel,key) for key in names],Library.name.label('library_name'),
        NovelPersonalData.rating.label('personal_rating'),state.label('follow_state')).order_by(*order).offset(offset).limit(limit).all()
    items=[dict(row._mapping) for row in rows]
    return {'items':items,'total':total,'offset':offset,'limit':limit,'library_total':library_total,'status_counts':{name:counts.get(name,0) for name in STATES}}


def options(db,user_id):
    libraries=db.query(Library.id,Library.name).filter_by(user_id=user_id).order_by(func.lower(Library.name),Library.id).limit(101).all()
    source=source_expression()
    sources=db.query(source).select_from(Novel).join(Library,Library.id==Novel.library_id).filter(Library.user_id==user_id,source.isnot(None)).distinct().order_by(source).limit(101).all()
    tags=db.query(NovelUserTag.tag).join(Novel,Novel.id==NovelUserTag.novel_id).join(Library,Library.id==Novel.library_id).filter(
        NovelUserTag.user_id==user_id,Library.user_id==user_id).distinct().order_by(NovelUserTag.tag).limit(201).all()
    return {'libraries':[{'id':row.id,'name':row.name} for row in libraries[:100]],
        'sources':[{'id':row[0],'label':'Local EPUB' if row[0]=='local' else SITE_LABELS.get(row[0],row[0])} for row in sources[:100]],
        'user_tags':[row[0] for row in tags[:200]],'libraries_truncated':len(libraries)>100,'sources_truncated':len(sources)>100,'user_tags_truncated':len(tags)>200}
