"""Local chapter lifecycle identity and reviewable topology transactions."""
from sqlalchemy.orm import Session
from sqlalchemy import Boolean, BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, event, inspect, text
from app.models.base import BaseModel
from config.database import Base


class ChapterManifestState(Base):
    __tablename__ = 'chapter_manifest_states'
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), primary_key=True)
    manifest_epoch = Column(String(36), nullable=False, unique=True)
    revision = Column(BigInteger, nullable=False, default=0, server_default='0')
    identity_required = Column(Boolean, nullable=False, default=False, server_default='0')
    ao3_material = Column(Boolean, nullable=False, default=False, server_default='0')
    metadata_source = Column(JSON, nullable=True)
    metadata_manifest_key = Column(String(36))
    metadata_revision = Column(String(64))
    metadata_fingerprint = Column(String(64))


class ChapterManifestReview(BaseModel):
    __tablename__ = 'chapter_manifest_reviews'
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), nullable=False, index=True)
    review_key = Column(String(36), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default='preview')
    revision = Column(Integer, nullable=False, default=1)
    fingerprint = Column(String(64), nullable=False)
    plan = Column(JSON, nullable=False)
    before_state = Column(JSON, nullable=True)
    after_fingerprint = Column(String(64), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    applied_at = Column(DateTime)
    undone_at = Column(DateTime)


class ChapterManifestOperation(BaseModel):
    __tablename__ = 'chapter_manifest_operations'
    __table_args__ = (UniqueConstraint('user_id', 'operation_id', name='uq_chapter_manifest_operation'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), nullable=False)
    operation_id = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)


class ChapterManifestReviewItem(BaseModel):
    __tablename__ = 'chapter_manifest_review_items'
    review_id = Column(Integer, ForeignKey('chapter_manifest_reviews.id', ondelete='CASCADE'), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    item_kind = Column(String(20), nullable=False)
    chapter_key = Column(String(36), nullable=True)
    metadata_chapter_key = Column(String(36), nullable=True)
    title = Column(String(1000), nullable=True)
    detail = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint('review_id','ordinal',name='uq_manifest_review_item_ordinal'),)


def install(connection):
    """Preserve lifecycle keys and topology generations for ORM and raw writes.

    The per-story counter is acquired after chapter row locks. Topology reviews
    use the same jobs -> chapters -> counter order; no database lock survives
    remote manifest fetching or user review.
    """
    if not {'novels','chapters','chapter_manifest_states'} <= set(inspect(connection).get_table_names()):
        return
    pg = connection.dialect.name == 'postgresql'
    uuid = 'gen_random_uuid()::text' if pg else "lower(hex(randomblob(4))||'-'||hex(randomblob(2))||'-'||hex(randomblob(2))||'-'||hex(randomblob(2))||'-'||hex(randomblob(6)))"
    connection.exec_driver_sql(f'INSERT INTO chapter_manifest_states(novel_id,manifest_epoch,revision,identity_required) SELECT id,{uuid},0,false FROM novels WHERE NOT EXISTS(SELECT 1 FROM chapter_manifest_states s WHERE s.novel_id=novels.id)')
    connection.exec_driver_sql(f'UPDATE chapters SET chapter_key={uuid} WHERE chapter_key IS NULL')
    # Conservative private provenance floor: retained originals outlive source relinks.
    def ao3_url(field):
        return '('+' OR '.join(f"lower(coalesce({field},'')) LIKE '{scheme}://{host}/%'" for scheme in ('http','https') for host in ('archiveofourown.org','www.archiveofourown.org'))+')'
    connection.execute(text("UPDATE chapter_manifest_states SET ao3_material=true WHERE ao3_material=false AND ("
        "EXISTS(SELECT 1 FROM novels n WHERE n.id=chapter_manifest_states.novel_id AND (lower(coalesce(n.site,'')) IN ('archive','ao3') OR lower(coalesce(n.novel_site,'')) IN ('archive','ao3') OR "+ao3_url('n.url')+' OR '+ao3_url('n.source_url')+')) OR '
        'EXISTS(SELECT 1 FROM chapters c WHERE c.novel_id=chapter_manifest_states.novel_id AND '+ao3_url('c.source_url')+') OR '
        'EXISTS(SELECT 1 FROM chapter_versions v JOIN chapters vc ON vc.id=v.chapter_id AND (v.chapter_key IS NULL OR v.chapter_key=vc.chapter_key) WHERE vc.novel_id=chapter_manifest_states.novel_id AND '+ao3_url('v.source_url')+'))'))
    changed = ('NEW.chapter_number IS DISTINCT FROM OLD.chapter_number OR NEW.archived IS DISTINCT FROM OLD.archived OR NEW.metadata_manifest_key IS DISTINCT FROM OLD.metadata_manifest_key OR NEW.metadata_chapter_key IS DISTINCT FROM OLD.metadata_chapter_key OR NEW.site_chapter_id IS DISTINCT FROM OLD.site_chapter_id OR NEW.source_url IS DISTINCT FROM OLD.source_url') if pg else ('NEW.chapter_number IS NOT OLD.chapter_number OR NEW.archived IS NOT OLD.archived OR NEW.metadata_manifest_key IS NOT OLD.metadata_manifest_key OR NEW.metadata_chapter_key IS NOT OLD.metadata_chapter_key OR NEW.site_chapter_id IS NOT OLD.site_chapter_id OR NEW.source_url IS NOT OLD.source_url')
    different=lambda field:(f'NEW.{field} IS DISTINCT FROM OLD.{field}' if pg else f'NEW.{field} IS NOT OLD.{field}')
    require_identity=' OR '.join([different('chapter_number'),different('archived'),*[
        f'(OLD.{field} IS NOT NULL AND ({different(field)}))' for field in
        ('metadata_manifest_key','metadata_chapter_key','site_chapter_id','source_url')]])
    changed += (' OR NEW.category IS DISTINCT FROM OLD.category OR NEW.title IS DISTINCT FROM OLD.title' if pg else ' OR NEW.category IS NOT OLD.category OR NEW.title IS NOT OLD.title')
    if pg:
        connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION nexus_local_chapter_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.chapter_key IS NOT NULL THEN RAISE EXCEPTION 'Chapter keys are database assigned'; END IF;
                NEW.chapter_key:={uuid};
            ELSIF TG_OP='UPDATE' THEN
                IF NEW.id<>OLD.id OR NEW.chapter_key IS DISTINCT FROM OLD.chapter_key OR NEW.novel_id<>OLD.novel_id THEN RAISE EXCEPTION 'Chapter lifecycle identity is immutable'; END IF;
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
        END $$''')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS nexus_local_chapter_identity ON chapters')
        connection.exec_driver_sql('CREATE TRIGGER nexus_local_chapter_identity BEFORE INSERT OR UPDATE OR DELETE ON chapters FOR EACH ROW EXECUTE FUNCTION nexus_local_chapter_identity()')
        connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION nexus_local_chapter_topology() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP='DELETE' THEN UPDATE chapter_manifest_states SET revision=revision+1,identity_required=true WHERE novel_id=OLD.novel_id;
            ELSIF TG_OP='INSERT' THEN UPDATE chapter_manifest_states SET revision=revision+1 WHERE novel_id=NEW.novel_id;
            ELSIF ({changed}) THEN UPDATE chapter_manifest_states SET revision=revision+1,identity_required=(identity_required OR ({require_identity})) WHERE novel_id=NEW.novel_id;
            END IF; RETURN NULL;
        END $$''')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS nexus_local_chapter_topology ON chapters')
        connection.exec_driver_sql('CREATE TRIGGER nexus_local_chapter_topology AFTER INSERT OR UPDATE OR DELETE ON chapters FOR EACH ROW EXECUTE FUNCTION nexus_local_chapter_topology()')
        connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION nexus_local_manifest_novel() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP='INSERT' THEN INSERT INTO chapter_manifest_states(novel_id,manifest_epoch,revision,identity_required) VALUES(NEW.id,{uuid},0,false);
            ELSE DELETE FROM chapter_manifest_states WHERE novel_id=OLD.id; END IF; RETURN NULL;
        END $$''')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS nexus_local_manifest_novel ON novels')
        connection.exec_driver_sql('CREATE TRIGGER nexus_local_manifest_novel AFTER INSERT OR DELETE ON novels FOR EACH ROW EXECUTE FUNCTION nexus_local_manifest_novel()')
        connection.exec_driver_sql("CREATE OR REPLACE FUNCTION nexus_local_manifest_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.manifest_epoch<>OLD.manifest_epoch OR NEW.novel_id<>OLD.novel_id OR NEW.revision<OLD.revision OR (OLD.identity_required AND NOT NEW.identity_required) OR (OLD.ao3_material AND NOT NEW.ao3_material) THEN RAISE EXCEPTION 'Manifest epoch is immutable and revision cannot decrease'; END IF; RETURN NEW; END $$")
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS nexus_local_manifest_guard ON chapter_manifest_states')
        connection.exec_driver_sql('CREATE TRIGGER nexus_local_manifest_guard BEFORE UPDATE ON chapter_manifest_states FOR EACH ROW EXECUTE FUNCTION nexus_local_manifest_guard()')
    else:
        for name in ('insert_guard','insert','update_guard','update','delete','novel_insert','novel_delete','state_guard'):
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS nexus_local_chapter_{name}')
        commands = {
            'insert_guard': "BEFORE INSERT ON chapters WHEN NEW.chapter_key IS NOT NULL BEGIN SELECT RAISE(ABORT,'Chapter keys are database assigned'); END",
            'insert': f'AFTER INSERT ON chapters BEGIN UPDATE chapters SET chapter_key={uuid} WHERE id=NEW.id; UPDATE chapter_manifest_states SET revision=revision+1 WHERE novel_id=NEW.novel_id; END',
            'update_guard': "BEFORE UPDATE ON chapters WHEN NEW.id<>OLD.id OR NEW.novel_id<>OLD.novel_id OR (OLD.chapter_key IS NOT NULL AND NEW.chapter_key IS NOT OLD.chapter_key) BEGIN SELECT RAISE(ABORT,'Chapter lifecycle identity is immutable'); END",
            'update': f'AFTER UPDATE ON chapters WHEN {changed} BEGIN UPDATE chapter_manifest_states SET revision=revision+1,identity_required=(identity_required OR ({require_identity})) WHERE novel_id=NEW.novel_id; END',
            'delete': 'AFTER DELETE ON chapters BEGIN UPDATE chapter_manifest_states SET revision=revision+1,identity_required=true WHERE novel_id=OLD.novel_id; END',
            'novel_insert': f'AFTER INSERT ON novels BEGIN INSERT INTO chapter_manifest_states(novel_id,manifest_epoch,revision,identity_required) VALUES(NEW.id,{uuid},0,false); END',
            'novel_delete': 'AFTER DELETE ON novels BEGIN DELETE FROM chapter_manifest_states WHERE novel_id=OLD.id; END',
            'state_guard': "BEFORE UPDATE ON chapter_manifest_states WHEN NEW.manifest_epoch<>OLD.manifest_epoch OR NEW.novel_id<>OLD.novel_id OR NEW.revision<OLD.revision OR typeof(NEW.revision)<>'integer' OR (OLD.identity_required AND NOT NEW.identity_required) OR (OLD.ao3_material AND NOT NEW.ao3_material) BEGIN SELECT RAISE(ABORT,'Manifest epoch is immutable and revision cannot decrease'); END",
        }
        for name, sql in commands.items():
            connection.exec_driver_sql(f'CREATE TRIGGER nexus_local_chapter_{name} {sql}')


def uninstall(connection):
    if connection.dialect.name == 'postgresql':
        for name,table in [('identity','chapters'),('topology','chapters')]:
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS nexus_local_chapter_{name} ON {table}')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS nexus_local_manifest_novel ON novels')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS nexus_local_manifest_guard ON chapter_manifest_states')
        for name in ('nexus_local_chapter_identity','nexus_local_chapter_topology','nexus_local_manifest_novel','nexus_local_manifest_guard'):
            connection.exec_driver_sql(f'DROP FUNCTION IF EXISTS {name}()')
    else:
        for name in ('insert_guard','insert','update_guard','update','delete','novel_insert','novel_delete','state_guard'):
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS nexus_local_chapter_{name}')


@event.listens_for(Base.metadata, 'after_create')
def install_after_create(metadata, connection, **kwargs):
    install(connection)


@event.listens_for(Session, 'do_orm_execute')
def active_chapters_by_default(execute_state):
    """Public ORM reads never acquire archived chapters by a reused ordinal.

    Explicit maintenance/archive access uses include_archived_chapters=True.
    Core SQL and durable history queries require their own reviewed predicates.
    """
    if (execute_state.is_select and not execute_state.execution_options.get('include_archived_chapters')
            and not execute_state.session.info.get('include_archived_chapters')):
        from sqlalchemy.orm import with_loader_criteria
        from app.models.chapter import Chapter
        execute_state.statement=execute_state.statement.options(with_loader_criteria(
            Chapter,lambda row:row.archived.is_(False),include_aliases=True))
