import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLibraryContext } from "../context/useLibraryContext";
import { useAuth } from "../context/AuthContext";
import { usePageTitle } from "../hooks/usePageTitle";
import { useUnreadUpdates } from "../hooks/useUnreadUpdates";
import { useSourceStatus } from "../hooks/useSourceStatus";
import { downloadService } from "../services/downloadService";
import { Button, CountBadge, EmptyState, PageHeader, Tabs, type TabItem } from "../components/ui";
import UpdatesInbox from "../components/activity/UpdatesInbox";
import NewWorksSection from "../components/follow/NewWorksSection";
import DownloadsTab from "../components/updates/DownloadsTab";
import ProblemsTab from "../components/updates/ProblemsTab";
import type { DownloadJob } from "../types/activity";
import "../styles/activity.css";

export type UpdatesTab = "new" | "downloads" | "problems";

const TAB_PATHS: Record<UpdatesTab, string> = {
  new: "/updates",
  downloads: "/updates/downloads",
  problems: "/updates/problems",
};

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many);

/** Updates destination: new chapters, downloads and problems. One tab per route. */
const Updates: React.FC<{ tab: UpdatesTab }> = ({ tab }) => {
  const navigate = useNavigate();
  const { activeLibrary } = useLibraryContext();
  const libraryId = activeLibrary?.id ?? null;
  const unread = useUnreadUpdates(libraryId);
  const { isAuthenticated } = useAuth();
  const sources = useSourceStatus(isAuthenticated);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const previous = useRef<{ failed: number; completed: number } | null>(null);

  usePageTitle("Updates");

  // Download queue, shared by the Downloads and Problems tabs. Polled so progress stays current.
  useEffect(() => {
    if (libraryId == null) { setJobs([]); return; }
    let cancelled = false;
    const load = () => {
      downloadService.listJobs(libraryId)
        .then((data) => { if (!cancelled && Array.isArray(data)) setJobs(data); })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [libraryId]);

  // Live region: announce new failures and completed chapters once each, not on every poll.
  useEffect(() => {
    const failed = jobs.filter((job) => job.status === "failed").length;
    const completed = jobs.filter((job) => job.status === "completed").length;
    const before = previous.current;
    previous.current = { failed, completed };
    if (!before) return;
    if (failed > before.failed) {
      const n = failed - before.failed;
      setAnnouncement(`${n} ${plural(n, "download", "downloads")} failed`);
    } else if (completed > before.completed) {
      const n = completed - before.completed;
      setAnnouncement(`${n} ${plural(n, "chapter", "chapters")} saved`);
    }
  }, [jobs]);

  const problemCount = jobs.filter((job) => job.status === "failed").length
    + sources.filter((status) => status.state !== "ok").length;

  const items: TabItem<UpdatesTab>[] = [
    {
      value: "new",
      label: <>New chapters{unread.count > 0 && <> <CountBadge count={unread.count} label={`${unread.count} ${plural(unread.count, "story", "stories")} with new chapters`} /></>}</>,
    },
    { value: "downloads", label: "Downloads" },
    {
      value: "problems",
      label: <>Problems{problemCount > 0 && <> <CountBadge count={problemCount} label={`${problemCount} ${plural(problemCount, "problem", "problems")}`} /></>}</>,
    },
  ];

  return <div className="updates-page">
    <PageHeader
      title="Updates"
      description="New chapters, downloads, and anything that needs attention."
      actions={<Button variant="ghost" size="sm" onClick={() => navigate("/settings/notifications")}>Notification settings</Button>}
    />
    <div className="visually-hidden" role="status" aria-live="polite">{announcement}</div>
    {!activeLibrary && <EmptyState level={3} title="No library selected" description="Create or select a library to see updates." />}
    {activeLibrary && libraryId != null && <>
      <Tabs
        label="Updates sections"
        items={items}
        value={tab}
        onChange={(next) => navigate(TAB_PATHS[next])}
      />
      {tab === "new" && <UpdatesInbox libraryId={libraryId} onChanged={() => void unread.reload()} />}
      {tab === "new" && <NewWorksSection />}
      {tab === "downloads" && <DownloadsTab jobs={jobs} setJobs={setJobs} />}
      {tab === "problems" && <ProblemsTab libraryId={libraryId} jobs={jobs} setJobs={setJobs} sources={sources.filter((status) => status.state !== "ok")} />}
    </>}
  </div>;
};

export default Updates;
