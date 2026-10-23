import { Link } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import React, { useEffect, useState } from "react";
import { Button, EmptyState } from "../ui";
import { downloadService } from "../../services/downloadService";
import { novelService } from "../../services/novelService";
import {
  describeSourceStatus,
  type SourceStatus,
} from "../../services/sourceStatusService";
import { displayTitle } from "../../utils/displayTitle";
import type { DownloadJob } from "../../types/activity";

interface ProblemsTabProps {
  libraryId: number;
  jobs: DownloadJob[];
  setJobs: React.Dispatch<React.SetStateAction<DownloadJob[]>>;
  /** Sites that are not healthy right now (state other than "ok"). */
  sources: SourceStatus[];
}

/** Failed downloads and source-site trouble, as plain sentences. */
const ProblemsTab: React.FC<ProblemsTabProps> = ({
  libraryId,
  jobs,
  setJobs,
  sources,
}) => {
  const { user } = useAuth();
  const sourceReview = (job: DownloadJob) =>
    /source_review_required|chapter_manifest_changed|source_manifest/i.test(
      `${job.error_code || ""} ${job.error || ""}`,
    );
  const [titles, setTitles] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const failed = jobs.filter((job) => job.status === "failed");

  useEffect(() => {
    let cancelled = false;
    novelService
      .getAllNovels(libraryId)
      .then((novels) => {
        if (cancelled || !Array.isArray(novels)) return;
        setTitles(
          Object.fromEntries(
            novels.map((novel) => [novel.id, displayTitle(novel)]),
          ),
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [libraryId]);

  const retry = async (job: DownloadJob) => {
    setBusyId(job.id);
    setError(null);
    try {
      const updated = await downloadService.retry(job.id);
      setJobs((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch {
      setError("That did not work. Try again.");
    } finally {
      setBusyId(null);
    }
  };

  if (failed.length === 0 && sources.length === 0) {
    return (
      <EmptyState
        level={3}
        title="No problems right now"
        description="Failed downloads and sites that are not responding show up here."
      />
    );
  }

  return (
    <div className="updates-problems">
      {error && (
        <p className="updates-inbox__error" role="alert">
          {error}
        </p>
      )}
      {sources.length > 0 && (
        <section aria-labelledby="updates-sources-title">
          <h2 id="updates-sources-title" className="updates-section__title">
            Sites
          </h2>
          <ul className="updates-problems__list">
            {sources.map((status) => (
              <li key={status.site} className="updates-problems__item">
                <strong>{status.label}</strong>
                <p>{describeSourceStatus(status)}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {failed.length > 0 && (
        <section aria-labelledby="updates-failed-title">
          <h2 id="updates-failed-title" className="updates-section__title">
            Failed downloads
          </h2>
          <ul className="updates-problems__list">
            {failed.map((job) => (
              <li key={job.id} className="updates-problems__item">
                <div>
                  <strong>{titles[job.novel_id] ?? "A story"}</strong>
                  {sourceReview(job) && (
                    <p>
                      Your saved chapter text is preserved. Source changes
                      require review before more downloads.{" "}
                      {user?.is_admin ? (
                        <Link to="/admin/plugins">Review source lifecycle</Link>
                      ) : (
                        "Ask your administrator to review this source."
                      )}{" "}
                      <Link
                        to={`/library/${libraryId}/novels/${job.novel_id}?tab=chapters`}
                      >
                        Review this story’s chapter changes
                      </Link>
                    </p>
                  )}
                  <p>
                    A chapter could not be saved.
                    {job.error ? ` ${job.error}` : ""}
                  </p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busyId === job.id}
                  onClick={() => void retry(job)}
                >
                  Retry
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};

export default ProblemsTab;
