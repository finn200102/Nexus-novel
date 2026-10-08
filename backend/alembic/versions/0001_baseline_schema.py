"""Baseline: the schema as it was when Alembic was adopted.

Every table is created only when missing. A fresh database gets the whole
schema; a pre-Alembic database (see app.db_migrations) has already been
brought up to date by the legacy compatibility step, so this revision only
fills in tables that installation never had. Never edit this revision; add a
new one instead.

Revision ID: 0001
Revises:
Create Date: 2026-10-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    def create_table(name, *columns, **kwargs):
        if name not in existing:
            op.create_table(name, *columns, **kwargs)

    def create_index(name, table, columns, **kwargs):
        if table not in existing:
            op.create_index(name, table, columns, **kwargs)

    create_table('authors',
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('site_author_id', sa.Integer(), nullable=True),
    sa.Column('site', sa.String(length=50), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_authors_id'), 'authors', ['id'], unique=False)
    create_index(op.f('ix_authors_name'), 'authors', ['name'], unique=True)
    create_table('genres',
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_genres_id'), 'genres', ['id'], unique=False)
    create_index(op.f('ix_genres_name'), 'genres', ['name'], unique=True)
    create_table('metadata_webhook_deliveries',
    sa.Column('delivery_key', sa.String(length=512), nullable=False),
    sa.Column('source_job_id', sa.String(length=255), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('claimed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('delivery_key', name='uq_metadata_webhook_delivery_key')
    )
    create_index(op.f('ix_metadata_webhook_deliveries_id'), 'metadata_webhook_deliveries', ['id'], unique=False)
    create_table('tags',
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_tags_id'), 'tags', ['id'], unique=False)
    create_index(op.f('ix_tags_name'), 'tags', ['name'], unique=True)
    create_table('users',
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('password', sa.String(length=255), nullable=False),
    sa.Column('is_admin', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    create_index(op.f('ix_users_password'), 'users', ['password'], unique=False)
    create_index(op.f('ix_users_username'), 'users', ['username'], unique=False)
    create_table('libraries',
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_libraries_user_name')
    )
    create_index(op.f('ix_libraries_id'), 'libraries', ['id'], unique=False)
    create_index(op.f('ix_libraries_name'), 'libraries', ['name'], unique=False)
    create_table('saved_searches',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('filters', sa.JSON(), nullable=False),
    sa.Column('notify_on_match', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_saved_search_user_name')
    )
    create_index(op.f('ix_saved_searches_id'), 'saved_searches', ['id'], unique=False)
    create_index(op.f('ix_saved_searches_user_id'), 'saved_searches', ['user_id'], unique=False)
    create_table('novels',
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('site_story_id', sa.BigInteger(), nullable=True),
    sa.Column('site', sa.String(length=255), nullable=True),
    sa.Column('url', sa.String(length=255), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cover_image', sa.String(length=255), nullable=True),
    sa.Column('file_path', sa.String(length=255), nullable=True),
    sa.Column('num_chapters', sa.Integer(), nullable=True),
    sa.Column('genre_id', sa.Integer(), nullable=True),
    sa.Column('library_id', sa.Integer(), nullable=False),
    sa.Column('metadata_id', sa.Integer(), nullable=True),
    sa.Column('scrape_status', sa.String(length=20), nullable=True),
    sa.Column('scrape_error', sa.String(length=500), nullable=True),
    sa.Column('author', sa.String(length=255), nullable=True),
    sa.Column('author_site_id', sa.BigInteger(), nullable=True),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('story_id', sa.BigInteger(), nullable=True),
    sa.Column('novel_site', sa.String(length=50), nullable=True),
    sa.Column('img_url', sa.String(length=500), nullable=True),
    sa.Column('word_count', sa.Integer(), nullable=True),
    sa.Column('reviews', sa.Integer(), nullable=True),
    sa.Column('favorites', sa.Integer(), nullable=True),
    sa.Column('follows', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=True),
    sa.Column('views', sa.Integer(), nullable=True),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('publish_date', sa.DateTime(), nullable=True),
    sa.Column('updated_date', sa.DateTime(), nullable=True),
    sa.Column('chapter_count', sa.Integer(), nullable=True),
    sa.Column('analyzed_at', sa.DateTime(), nullable=True),
    sa.Column('analysis_type', sa.String(length=50), nullable=True),
    sa.Column('analyzed_chapter_count', sa.Integer(), nullable=True),
    sa.Column('parsed_at', sa.DateTime(), nullable=True),
    sa.Column('follow_state', sa.String(length=20), server_default='plan_to_read', nullable=False),
    sa.Column('followed_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['author_id'], ['authors.id'], ),
    sa.ForeignKeyConstraint(['genre_id'], ['genres.id'], ),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('library_id', 'url', name='uq_novels_library_url')
    )
    create_index(op.f('ix_novels_id'), 'novels', ['id'], unique=False)
    create_index(op.f('ix_novels_metadata_id'), 'novels', ['metadata_id'], unique=False)
    create_index(op.f('ix_novels_title'), 'novels', ['title'], unique=False)
    create_table('chapters',
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('chapter_number', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=True),
    sa.Column('site_chapter_id', sa.BigInteger(), nullable=True),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('word_count', sa.Integer(), nullable=True),
    sa.Column('content_status', sa.Enum('MISSING', 'PRESENT', 'PROCESSING', 'FAILED', name='contentstatus'), nullable=False),
    sa.Column('audio_status', sa.Enum('MISSING', 'PRESENT', 'PROCESSING', 'FAILED', name='audiostatus'), nullable=False),
    sa.Column('download_started_at', sa.DateTime(), nullable=True),
    sa.Column('download_finished_at', sa.DateTime(), nullable=True),
    sa.Column('download_error', sa.String(length=1000), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('novel_id', 'chapter_number', name='uix_chapter_novel_number')
    )
    create_index(op.f('ix_chapters_id'), 'chapters', ['id'], unique=False)
    create_table('novel_tag',
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('tag_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ),
    sa.PrimaryKeyConstraint('novel_id', 'tag_id')
    )
    create_table('novel_update_events',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('chapter_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('first_chapter_number', sa.Integer(), nullable=True),
    sa.Column('last_chapter_number', sa.Integer(), nullable=True),
    sa.Column('message', sa.Text(), server_default='', nullable=False),
    sa.Column('details', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('read_at', sa.DateTime(), nullable=True),
    sa.Column('notification_visible', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_novel_update_events_id'), 'novel_update_events', ['id'], unique=False)
    create_table('reading_history',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('chapter_number', sa.Integer(), nullable=False),
    sa.Column('reading_date', sa.DateTime(), nullable=False),
    sa.Column('max_percent', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'novel_id', 'chapter_number', 'reading_date', name='uq_reading_history_day')
    )
    create_index(op.f('ix_reading_history_id'), 'reading_history', ['id'], unique=False)
    create_table('user_novel_follows',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=20), server_default='plan_to_read', nullable=False),
    sa.Column('followed_at', sa.DateTime(), nullable=True),
    sa.Column('download_policy', sa.String(length=20), server_default='none', nullable=False),
    sa.Column('download_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('notification_policy', sa.String(length=20), server_default='immediate', nullable=False),
    sa.Column('notification_count', sa.Integer(), server_default='1', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'novel_id', name='uq_user_novel_follow')
    )
    create_index(op.f('ix_user_novel_follows_id'), 'user_novel_follows', ['id'], unique=False)
    create_table('chapter_audio_jobs',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('library_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('chapter_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
    sa.Column('provider_id', sa.String(length=80), nullable=False),
    sa.Column('provider_url', sa.String(length=1000), nullable=False),
    sa.Column('provider_model', sa.String(length=255), nullable=False),
    sa.Column('provider_voice', sa.String(length=255), nullable=False),
    sa.Column('provider_language', sa.String(length=64), nullable=True),
    sa.Column('total_parts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('completed_parts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('audio_path', sa.String(length=1000), nullable=True),
    sa.Column('audio_bytes', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    create_index('ix_audio_jobs_queue', 'chapter_audio_jobs', ['status', 'next_attempt_at', 'created_at'], unique=False)
    create_index(op.f('ix_chapter_audio_jobs_id'), 'chapter_audio_jobs', ['id'], unique=False)
    create_table('chapter_download_jobs',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('library_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('chapter_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('cancellation_reason', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_chapter_download_jobs_id'), 'chapter_download_jobs', ['id'], unique=False)
    create_table('reading_annotations',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('chapter_id', sa.Integer(), nullable=False),
    sa.Column('annotation_type', sa.String(length=20), server_default='bookmark', nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('percent', sa.Float(), server_default='0', nullable=False),
    sa.Column('quote', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_reading_annotations_id'), 'reading_annotations', ['id'], unique=False)
    create_table('reading_progress',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('chapter_id', sa.Integer(), nullable=True),
    sa.Column('chapter_number', sa.Integer(), nullable=True),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('percent', sa.Float(), server_default='0', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'novel_id', name='uq_user_novel_progress')
    )
    create_index(op.f('ix_reading_progress_id'), 'reading_progress', ['id'], unique=False)
    create_table('chapter_audio_parts',
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('part_index', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
    sa.Column('audio_path', sa.String(length=1000), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['chapter_audio_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'part_index', name='uq_audio_job_part')
    )
    create_index(op.f('ix_chapter_audio_parts_id'), 'chapter_audio_parts', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_chapter_audio_parts_id'), table_name='chapter_audio_parts')
    op.drop_table('chapter_audio_parts')
    op.drop_index(op.f('ix_reading_progress_id'), table_name='reading_progress')
    op.drop_table('reading_progress')
    op.drop_index(op.f('ix_reading_annotations_id'), table_name='reading_annotations')
    op.drop_table('reading_annotations')
    op.drop_index(op.f('ix_chapter_download_jobs_id'), table_name='chapter_download_jobs')
    op.drop_table('chapter_download_jobs')
    op.drop_index(op.f('ix_chapter_audio_jobs_id'), table_name='chapter_audio_jobs')
    op.drop_index('ix_audio_jobs_queue', table_name='chapter_audio_jobs')
    op.drop_table('chapter_audio_jobs')
    op.drop_index(op.f('ix_user_novel_follows_id'), table_name='user_novel_follows')
    op.drop_table('user_novel_follows')
    op.drop_index(op.f('ix_reading_history_id'), table_name='reading_history')
    op.drop_table('reading_history')
    op.drop_index(op.f('ix_novel_update_events_id'), table_name='novel_update_events')
    op.drop_table('novel_update_events')
    op.drop_table('novel_tag')
    op.drop_index(op.f('ix_chapters_id'), table_name='chapters')
    op.drop_table('chapters')
    op.drop_index(op.f('ix_novels_title'), table_name='novels')
    op.drop_index(op.f('ix_novels_metadata_id'), table_name='novels')
    op.drop_index(op.f('ix_novels_id'), table_name='novels')
    op.drop_table('novels')
    op.drop_index(op.f('ix_saved_searches_user_id'), table_name='saved_searches')
    op.drop_index(op.f('ix_saved_searches_id'), table_name='saved_searches')
    op.drop_table('saved_searches')
    op.drop_index(op.f('ix_libraries_name'), table_name='libraries')
    op.drop_index(op.f('ix_libraries_id'), table_name='libraries')
    op.drop_table('libraries')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_password'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_tags_name'), table_name='tags')
    op.drop_index(op.f('ix_tags_id'), table_name='tags')
    op.drop_table('tags')
    op.drop_index(op.f('ix_metadata_webhook_deliveries_id'), table_name='metadata_webhook_deliveries')
    op.drop_table('metadata_webhook_deliveries')
    op.drop_index(op.f('ix_genres_name'), table_name='genres')
    op.drop_index(op.f('ix_genres_id'), table_name='genres')
    op.drop_table('genres')
    op.drop_index(op.f('ix_authors_name'), table_name='authors')
    op.drop_index(op.f('ix_authors_id'), table_name='authors')
    op.drop_table('authors')
    sa.Enum(name='audiostatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='contentstatus').drop(op.get_bind(), checkfirst=True)
