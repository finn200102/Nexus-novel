from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.audio_job import ChapterAudioJob
from app.models.user import User
from app.services import podcast_service as service
from app.services import podcast_audio_service as audio
from app.models.podcast_audio import PodcastAudioJob
from app.schemas.podcast_audio import PodcastStatus, PodcastEpisodeStatus
from config.database import get_db

router = APIRouter(tags=["private podcasts"])


@router.get("/audio/stories/{novel_id}/podcast", response_model=PodcastStatus)
def podcast_status(novel_id: int, response: Response, offset: int=Query(0,ge=0), limit: int=Query(50,ge=1,le=200),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.owned_story(db, user.id, novel_id)
    response.headers.update(service.PRIVATE_HEADERS)
    return audio.status(db, user.id, novel_id,offset=offset,limit=limit)


@router.post("/audio/stories/{novel_id}/podcast", status_code=201, response_model=PodcastStatus)
def rotate_podcast(novel_id: int, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    token = service.rotate(db, user.id, novel_id)
    audio.activate(db, user.id, novel_id)
    response.headers.update(service.PRIVATE_HEADERS)
    return {**audio.status(db,user.id,novel_id), "feed_url": f"{service.public_api_base(request)}/podcasts/{token}/feed.xml"}


@router.delete("/audio/stories/{novel_id}/podcast", status_code=204)
def revoke_podcast(novel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.owned_story(db, user.id, novel_id)
    row = service.token_row(db, user.id, novel_id)
    audio.cancel_podcast_audio(db,user.id,novel_id)
    if row:
        db.delete(row)
    db.commit()
    return Response(status_code=204, headers=service.PRIVATE_HEADERS)


@router.post("/audio/stories/{novel_id}/podcast/episodes/{episode_id}/retry", response_model=PodcastEpisodeStatus)
def retry_episode(novel_id: int, episode_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.owned_story(db,user.id,novel_id)
    job=db.query(PodcastAudioJob).filter_by(id=episode_id,user_id=user.id,novel_id=novel_id).first()
    if job is None:raise HTTPException(404,"Podcast episode not found")
    if service.token_row(db,user.id,novel_id) is None:raise HTTPException(409,"Enable the private feed before preparing episodes")
    if audio.latest_sources(db,user.id,novel_id).filter(ChapterAudioJob.id==job.source_audio_job_id).first() is None:
        raise HTTPException(409,"This episode belongs to an archived or superseded recording. Its completed private file remains available.")
    if job.status not in ("failed","retry_wait","cancelled") and not (job.status=="completed" and audio.ready_file(job) is None):
        raise HTTPException(409,"This episode is not waiting for a retry")
    job.status="queued";job.error=None;job.error_code=None;job.finished_at=None
    job.lease_owner=None;job.lease_expires_at=None;job.attempt_count=0;job.next_attempt_at=None
    db.commit();db.refresh(job)
    return PodcastEpisodeStatus(id=job.id,source_audio_job_id=job.source_audio_job_id,chapter_number=job.chapter_number,
        status=job.status,audio_bytes=job.audio_bytes,duration_seconds=job.duration_seconds,error=None,error_code=None)


@router.api_route("/podcasts/{token}/feed.xml", methods=["GET", "HEAD"])
def podcast_feed(token: str, request: Request, db: Session = Depends(get_db)):
    row = service.authenticate(db, request, token)
    return Response(service.build_feed(db, row, token, service.public_api_base(request)),
                    media_type="application/rss+xml", headers=service.PRIVATE_HEADERS)


@router.api_route("/podcasts/{token}/audio/{job_id}", methods=["GET", "HEAD"])
@router.api_route("/podcasts/{token}/audio/{job_id}.mp3", methods=["GET", "HEAD"])
def podcast_audio(token: str, job_id: int, request: Request, db: Session = Depends(get_db)):
    row = service.authenticate(db, request, token)
    job = db.query(ChapterAudioJob).filter_by(id=job_id, user_id=row.user_id, novel_id=row.novel_id).first()
    derivative = db.query(PodcastAudioJob).filter_by(source_audio_job_id=job_id,user_id=row.user_id,
        novel_id=row.novel_id,pipeline_version=audio.PIPELINE).first() if job and job.status=="completed" else None
    path = audio.ready_file(derivative)
    if path is None:
        raise HTTPException(404, "Recording not found", headers=service.PRIVATE_HEADERS)
    return FileResponse(path, media_type="audio/mpeg", filename=f"chapter-{derivative.chapter_number}.mp3",
        content_disposition_type="inline", headers=service.PRIVATE_HEADERS)
