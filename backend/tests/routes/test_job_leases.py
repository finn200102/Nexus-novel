from datetime import timedelta
from sqlalchemy.orm import sessionmaker
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.download_job import ChapterDownloadJob
from app.services.download_job_service import claim_job
from app.services.job_lease import recover_expired, utcnow


def test_only_one_worker_claims_and_expired_work_is_recovered(db, test_user, test_library):
    novel = Novel(title="Lease", library_id=test_library.id)
    db.add(novel)
    db.flush()
    chapter = Chapter(novel_id=novel.id, chapter_number=1)
    db.add(chapter)
    db.flush()
    job = ChapterDownloadJob(user_id=test_user.id, library_id=test_library.id, novel_id=novel.id, chapter_id=chapter.id)
    db.add(job)
    db.commit()
    other = sessionmaker(bind=db.get_bind())()
    try:
        owned = claim_job(db, job.id, worker_id="first")
        assert owned.lease_owner == "first"
        assert claim_job(other, job.id, worker_id="second") is None
        owned.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert recover_expired(db, ChapterDownloadJob) == 1
        recovered = claim_job(other, job.id, worker_id="second")
        assert recovered.lease_owner == "second"
        assert recovered.attempt_count == 2
    finally:
        other.close()
