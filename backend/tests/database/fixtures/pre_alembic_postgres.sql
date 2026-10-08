-- Schema of a pre-Alembic Nexus Novel database (pg_dump --schema-only of a
-- local install, October 2026, owner statements removed). Used by
-- tests/database/test_migrations.py to test the legacy upgrade path.

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

CREATE TYPE public.audiostatus AS ENUM (
    'MISSING',
    'PRESENT',
    'PROCESSING',
    'FAILED'
);

CREATE TYPE public.contentstatus AS ENUM (
    'MISSING',
    'PRESENT',
    'PROCESSING',
    'FAILED'
);

SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE public.authors (
    name character varying(100) NOT NULL,
    site_author_id integer,
    site character varying(50),
    description text,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.authors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.authors_id_seq OWNED BY public.authors.id;

CREATE TABLE public.chapter_audio_jobs (
    user_id integer NOT NULL,
    library_id integer NOT NULL,
    novel_id integer NOT NULL,
    chapter_id integer NOT NULL,
    status character varying(20) DEFAULT 'queued'::character varying NOT NULL,
    provider_id character varying(80) NOT NULL,
    provider_url character varying(1000) NOT NULL,
    provider_model character varying(255) NOT NULL,
    provider_voice character varying(255) NOT NULL,
    provider_language character varying(64),
    total_parts integer DEFAULT 0 NOT NULL,
    completed_parts integer DEFAULT 0 NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    next_attempt_at timestamp without time zone,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    cancelled_at timestamp without time zone,
    error_code character varying(80),
    error text,
    audio_path character varying(1000),
    audio_bytes integer,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.chapter_audio_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.chapter_audio_jobs_id_seq OWNED BY public.chapter_audio_jobs.id;

CREATE TABLE public.chapter_audio_parts (
    job_id integer NOT NULL,
    part_index integer NOT NULL,
    text text NOT NULL,
    status character varying(20) DEFAULT 'queued'::character varying NOT NULL,
    audio_path character varying(1000),
    error text,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.chapter_audio_parts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.chapter_audio_parts_id_seq OWNED BY public.chapter_audio_parts.id;

CREATE TABLE public.chapter_download_jobs (
    user_id integer NOT NULL,
    library_id integer NOT NULL,
    novel_id integer NOT NULL,
    chapter_id integer NOT NULL,
    status character varying(20) DEFAULT 'queued'::character varying NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    next_attempt_at timestamp without time zone,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    last_attempt_at timestamp without time zone,
    cancelled_at timestamp without time zone,
    cancellation_reason text,
    error_code character varying(80),
    error text,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.chapter_download_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.chapter_download_jobs_id_seq OWNED BY public.chapter_download_jobs.id;

CREATE TABLE public.chapters (
    title character varying(255),
    content text,
    chapter_number integer NOT NULL,
    novel_id integer,
    site_chapter_id bigint,
    source_url character varying(500),
    word_count integer,
    content_status public.contentstatus NOT NULL,
    audio_status public.audiostatus NOT NULL,
    download_started_at timestamp without time zone,
    download_finished_at timestamp without time zone,
    download_error character varying(1000),
    retry_count integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.chapters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.chapters_id_seq OWNED BY public.chapters.id;

CREATE TABLE public.genres (
    name character varying(50) NOT NULL,
    description text,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.genres_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.genres_id_seq OWNED BY public.genres.id;

CREATE TABLE public.libraries (
    name character varying(100) NOT NULL,
    user_id integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.libraries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.libraries_id_seq OWNED BY public.libraries.id;

CREATE TABLE public.metadata_webhook_deliveries (
    delivery_key character varying(512) NOT NULL,
    source_job_id character varying(255) NOT NULL,
    source_id integer NOT NULL,
    event_type character varying(80) NOT NULL,
    claimed_at timestamp without time zone DEFAULT now() NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.metadata_webhook_deliveries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.metadata_webhook_deliveries_id_seq OWNED BY public.metadata_webhook_deliveries.id;

CREATE TABLE public.novel_tag (
    novel_id integer NOT NULL,
    tag_id integer NOT NULL
);

CREATE TABLE public.novel_update_events (
    user_id integer NOT NULL,
    novel_id integer NOT NULL,
    event_type character varying(40) NOT NULL,
    chapter_count integer DEFAULT 0 NOT NULL,
    first_chapter_number integer,
    last_chapter_number integer,
    message text DEFAULT ''::text NOT NULL,
    details json DEFAULT '{}'::json NOT NULL,
    read_at timestamp without time zone,
    notification_visible boolean DEFAULT true NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.novel_update_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.novel_update_events_id_seq OWNED BY public.novel_update_events.id;

CREATE TABLE public.novels (
    title character varying(255) NOT NULL,
    author_id integer,
    site_story_id bigint,
    site character varying(255),
    url character varying(255),
    description text,
    cover_image character varying(255),
    file_path character varying(255),
    num_chapters integer,
    genre_id integer,
    library_id integer NOT NULL,
    metadata_id integer,
    scrape_status character varying(20),
    scrape_error character varying(500),
    author character varying(255),
    author_site_id bigint,
    source_url character varying(500),
    story_id bigint,
    novel_site character varying(50),
    img_url character varying(500),
    word_count integer,
    reviews integer,
    favorites integer,
    follows integer,
    status character varying(50),
    views integer,
    rating integer,
    publish_date timestamp without time zone,
    updated_date timestamp without time zone,
    chapter_count integer,
    analyzed_at timestamp without time zone,
    analysis_type character varying(50),
    analyzed_chapter_count integer,
    parsed_at timestamp without time zone,
    follow_state character varying(20) DEFAULT 'plan_to_read'::character varying NOT NULL,
    followed_at timestamp without time zone,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.novels_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.novels_id_seq OWNED BY public.novels.id;

CREATE TABLE public.reading_annotations (
    user_id integer NOT NULL,
    novel_id integer NOT NULL,
    chapter_id integer NOT NULL,
    annotation_type character varying(20) DEFAULT 'bookmark'::character varying NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    percent double precision DEFAULT '0'::double precision NOT NULL,
    quote text,
    note text,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.reading_annotations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.reading_annotations_id_seq OWNED BY public.reading_annotations.id;

CREATE TABLE public.reading_history (
    user_id integer NOT NULL,
    novel_id integer NOT NULL,
    chapter_number integer NOT NULL,
    reading_date timestamp without time zone NOT NULL,
    max_percent integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.reading_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.reading_history_id_seq OWNED BY public.reading_history.id;

CREATE TABLE public.reading_progress (
    user_id integer NOT NULL,
    novel_id integer NOT NULL,
    chapter_id integer,
    chapter_number integer,
    "position" integer DEFAULT 0 NOT NULL,
    percent double precision DEFAULT '0'::double precision NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.reading_progress_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.reading_progress_id_seq OWNED BY public.reading_progress.id;

CREATE TABLE public.saved_searches (
    user_id integer NOT NULL,
    name character varying(120) NOT NULL,
    filters json NOT NULL,
    notify_on_match boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.saved_searches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.saved_searches_id_seq OWNED BY public.saved_searches.id;

CREATE TABLE public.tags (
    name character varying(50) NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tags_id_seq OWNED BY public.tags.id;

CREATE TABLE public.user_novel_follows (
    user_id integer NOT NULL,
    novel_id integer NOT NULL,
    state character varying(20) DEFAULT 'plan_to_read'::character varying NOT NULL,
    followed_at timestamp without time zone,
    download_policy character varying(20) DEFAULT 'none'::character varying NOT NULL,
    download_count integer DEFAULT 0 NOT NULL,
    notification_policy character varying(20) DEFAULT 'immediate'::character varying NOT NULL,
    notification_count integer DEFAULT 1 NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.user_novel_follows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_novel_follows_id_seq OWNED BY public.user_novel_follows.id;

CREATE TABLE public.users (
    username character varying(100) NOT NULL,
    password character varying(255) NOT NULL,
    is_admin boolean DEFAULT false NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

ALTER TABLE ONLY public.authors ALTER COLUMN id SET DEFAULT nextval('public.authors_id_seq'::regclass);

ALTER TABLE ONLY public.chapter_audio_jobs ALTER COLUMN id SET DEFAULT nextval('public.chapter_audio_jobs_id_seq'::regclass);

ALTER TABLE ONLY public.chapter_audio_parts ALTER COLUMN id SET DEFAULT nextval('public.chapter_audio_parts_id_seq'::regclass);

ALTER TABLE ONLY public.chapter_download_jobs ALTER COLUMN id SET DEFAULT nextval('public.chapter_download_jobs_id_seq'::regclass);

ALTER TABLE ONLY public.chapters ALTER COLUMN id SET DEFAULT nextval('public.chapters_id_seq'::regclass);

ALTER TABLE ONLY public.genres ALTER COLUMN id SET DEFAULT nextval('public.genres_id_seq'::regclass);

ALTER TABLE ONLY public.libraries ALTER COLUMN id SET DEFAULT nextval('public.libraries_id_seq'::regclass);

ALTER TABLE ONLY public.metadata_webhook_deliveries ALTER COLUMN id SET DEFAULT nextval('public.metadata_webhook_deliveries_id_seq'::regclass);

ALTER TABLE ONLY public.novel_update_events ALTER COLUMN id SET DEFAULT nextval('public.novel_update_events_id_seq'::regclass);

ALTER TABLE ONLY public.novels ALTER COLUMN id SET DEFAULT nextval('public.novels_id_seq'::regclass);

ALTER TABLE ONLY public.reading_annotations ALTER COLUMN id SET DEFAULT nextval('public.reading_annotations_id_seq'::regclass);

ALTER TABLE ONLY public.reading_history ALTER COLUMN id SET DEFAULT nextval('public.reading_history_id_seq'::regclass);

ALTER TABLE ONLY public.reading_progress ALTER COLUMN id SET DEFAULT nextval('public.reading_progress_id_seq'::regclass);

ALTER TABLE ONLY public.saved_searches ALTER COLUMN id SET DEFAULT nextval('public.saved_searches_id_seq'::regclass);

ALTER TABLE ONLY public.tags ALTER COLUMN id SET DEFAULT nextval('public.tags_id_seq'::regclass);

ALTER TABLE ONLY public.user_novel_follows ALTER COLUMN id SET DEFAULT nextval('public.user_novel_follows_id_seq'::regclass);

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER TABLE ONLY public.authors
    ADD CONSTRAINT authors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.chapter_audio_jobs
    ADD CONSTRAINT chapter_audio_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.chapter_audio_parts
    ADD CONSTRAINT chapter_audio_parts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.chapter_download_jobs
    ADD CONSTRAINT chapter_download_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.chapters
    ADD CONSTRAINT chapters_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.genres
    ADD CONSTRAINT genres_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.libraries
    ADD CONSTRAINT libraries_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.metadata_webhook_deliveries
    ADD CONSTRAINT metadata_webhook_deliveries_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.novel_tag
    ADD CONSTRAINT novel_tag_pkey PRIMARY KEY (novel_id, tag_id);

ALTER TABLE ONLY public.novel_update_events
    ADD CONSTRAINT novel_update_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.novels
    ADD CONSTRAINT novels_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.reading_annotations
    ADD CONSTRAINT reading_annotations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.reading_history
    ADD CONSTRAINT reading_history_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.reading_progress
    ADD CONSTRAINT reading_progress_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.saved_searches
    ADD CONSTRAINT saved_searches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.chapters
    ADD CONSTRAINT uix_chapter_novel_number UNIQUE (novel_id, chapter_number);

ALTER TABLE ONLY public.chapter_audio_parts
    ADD CONSTRAINT uq_audio_job_part UNIQUE (job_id, part_index);

ALTER TABLE ONLY public.libraries
    ADD CONSTRAINT uq_libraries_user_name UNIQUE (user_id, name);

ALTER TABLE ONLY public.metadata_webhook_deliveries
    ADD CONSTRAINT uq_metadata_webhook_delivery_key UNIQUE (delivery_key);

ALTER TABLE ONLY public.novels
    ADD CONSTRAINT uq_novels_library_url UNIQUE (library_id, url);

ALTER TABLE ONLY public.reading_history
    ADD CONSTRAINT uq_reading_history_day UNIQUE (user_id, novel_id, chapter_number, reading_date);

ALTER TABLE ONLY public.saved_searches
    ADD CONSTRAINT uq_saved_search_user_name UNIQUE (user_id, name);

ALTER TABLE ONLY public.user_novel_follows
    ADD CONSTRAINT uq_user_novel_follow UNIQUE (user_id, novel_id);

ALTER TABLE ONLY public.reading_progress
    ADD CONSTRAINT uq_user_novel_progress UNIQUE (user_id, novel_id);

ALTER TABLE ONLY public.user_novel_follows
    ADD CONSTRAINT user_novel_follows_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

CREATE INDEX ix_audio_jobs_queue ON public.chapter_audio_jobs USING btree (status, next_attempt_at, created_at);

CREATE INDEX ix_authors_id ON public.authors USING btree (id);

CREATE UNIQUE INDEX ix_authors_name ON public.authors USING btree (name);

CREATE INDEX ix_chapter_audio_jobs_id ON public.chapter_audio_jobs USING btree (id);

CREATE INDEX ix_chapter_audio_parts_id ON public.chapter_audio_parts USING btree (id);

CREATE INDEX ix_chapter_download_jobs_id ON public.chapter_download_jobs USING btree (id);

CREATE INDEX ix_chapters_id ON public.chapters USING btree (id);

CREATE INDEX ix_genres_id ON public.genres USING btree (id);

CREATE UNIQUE INDEX ix_genres_name ON public.genres USING btree (name);

CREATE INDEX ix_libraries_id ON public.libraries USING btree (id);

CREATE INDEX ix_libraries_name ON public.libraries USING btree (name);

CREATE INDEX ix_metadata_webhook_deliveries_id ON public.metadata_webhook_deliveries USING btree (id);

CREATE INDEX ix_novel_update_events_id ON public.novel_update_events USING btree (id);

CREATE INDEX ix_novels_id ON public.novels USING btree (id);

CREATE INDEX ix_novels_metadata_id ON public.novels USING btree (metadata_id);

CREATE INDEX ix_novels_title ON public.novels USING btree (title);

CREATE INDEX ix_reading_annotations_id ON public.reading_annotations USING btree (id);

CREATE INDEX ix_reading_history_id ON public.reading_history USING btree (id);

CREATE INDEX ix_reading_progress_id ON public.reading_progress USING btree (id);

CREATE INDEX ix_saved_searches_id ON public.saved_searches USING btree (id);

CREATE INDEX ix_saved_searches_user_id ON public.saved_searches USING btree (user_id);

CREATE INDEX ix_tags_id ON public.tags USING btree (id);

CREATE UNIQUE INDEX ix_tags_name ON public.tags USING btree (name);

CREATE INDEX ix_user_novel_follows_id ON public.user_novel_follows USING btree (id);

CREATE INDEX ix_users_id ON public.users USING btree (id);

CREATE INDEX ix_users_password ON public.users USING btree (password);

CREATE INDEX ix_users_username ON public.users USING btree (username);

ALTER TABLE ONLY public.chapter_audio_jobs
    ADD CONSTRAINT chapter_audio_jobs_chapter_id_fkey FOREIGN KEY (chapter_id) REFERENCES public.chapters(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_audio_jobs
    ADD CONSTRAINT chapter_audio_jobs_library_id_fkey FOREIGN KEY (library_id) REFERENCES public.libraries(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_audio_jobs
    ADD CONSTRAINT chapter_audio_jobs_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_audio_jobs
    ADD CONSTRAINT chapter_audio_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_audio_parts
    ADD CONSTRAINT chapter_audio_parts_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.chapter_audio_jobs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_download_jobs
    ADD CONSTRAINT chapter_download_jobs_chapter_id_fkey FOREIGN KEY (chapter_id) REFERENCES public.chapters(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_download_jobs
    ADD CONSTRAINT chapter_download_jobs_library_id_fkey FOREIGN KEY (library_id) REFERENCES public.libraries(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_download_jobs
    ADD CONSTRAINT chapter_download_jobs_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapter_download_jobs
    ADD CONSTRAINT chapter_download_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chapters
    ADD CONSTRAINT chapters_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id);

ALTER TABLE ONLY public.libraries
    ADD CONSTRAINT libraries_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.novel_tag
    ADD CONSTRAINT novel_tag_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id);

ALTER TABLE ONLY public.novel_tag
    ADD CONSTRAINT novel_tag_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id);

ALTER TABLE ONLY public.novel_update_events
    ADD CONSTRAINT novel_update_events_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.novel_update_events
    ADD CONSTRAINT novel_update_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.novels
    ADD CONSTRAINT novels_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.authors(id);

ALTER TABLE ONLY public.novels
    ADD CONSTRAINT novels_genre_id_fkey FOREIGN KEY (genre_id) REFERENCES public.genres(id);

ALTER TABLE ONLY public.novels
    ADD CONSTRAINT novels_library_id_fkey FOREIGN KEY (library_id) REFERENCES public.libraries(id);

ALTER TABLE ONLY public.reading_annotations
    ADD CONSTRAINT reading_annotations_chapter_id_fkey FOREIGN KEY (chapter_id) REFERENCES public.chapters(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reading_annotations
    ADD CONSTRAINT reading_annotations_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reading_annotations
    ADD CONSTRAINT reading_annotations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reading_history
    ADD CONSTRAINT reading_history_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reading_history
    ADD CONSTRAINT reading_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reading_progress
    ADD CONSTRAINT reading_progress_chapter_id_fkey FOREIGN KEY (chapter_id) REFERENCES public.chapters(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reading_progress
    ADD CONSTRAINT reading_progress_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reading_progress
    ADD CONSTRAINT reading_progress_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.saved_searches
    ADD CONSTRAINT saved_searches_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_novel_follows
    ADD CONSTRAINT user_novel_follows_novel_id_fkey FOREIGN KEY (novel_id) REFERENCES public.novels(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_novel_follows
    ADD CONSTRAINT user_novel_follows_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

