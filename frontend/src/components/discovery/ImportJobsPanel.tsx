import React, { useCallback, useEffect, useState } from "react";
import { getUserFacingError } from "../../services/apiClient";
import { ImportJob, liveSearchService } from "../../services/liveSearchService";

type Source = "url_list" | "rr_list" | "epub" | "ao3_bookmarks" | "ffn_favorites";

const SOURCES: Array<{ value: Source; label: string; hint: string }> = [
  { value: "url_list", label: "URLs / CSV", hint: "Paste story links or a CSV export; every link is imported." },
  { value: "rr_list", label: "Royal Road list", hint: "Paste your Royal Road follows or favorites page text." },
  { value: "epub", label: "EPUB files", hint: "FanFicFare and FicHub EPUBs carry the original story URL." },
  { value: "ao3_bookmarks", label: "AO3 bookmarks", hint: "Public bookmarks of an AO3 user, fetched page by page." },
  { value: "ffn_favorites", label: "FFN favorites", hint: "Public favorites of a FanFiction.net profile (numeric user id)." },
];

const ACTIVE = ["queued", "expanding", "running"];

interface Props {
  libraryId: number | null;
  onError: (message: string) => void;
}

export const ImportJobsPanel: React.FC<Props> = ({ libraryId, onError }) => {
  const [source, setSource] = useState<Source>("url_list");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [open, setOpen] = useState<ImportJob | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setJobs(await liveSearchService.jobs());
    } catch {
      /* the list is informational; the next poll retries */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasActive = jobs.some((job) => ACTIVE.includes(job.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [hasActive, refresh]);

  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!libraryId) {
      onError("Please select a library first");
      return;
    }
    setBusy(true);
    try {
      let job: ImportJob;
      if (source === "epub") job = await liveSearchService.importEpubs(libraryId, files);
      else if (source === "ao3_bookmarks" || source === "ffn_favorites") job = await liveSearchService.importList(libraryId, source, text.trim());
      else job = await liveSearchService.importUrls(libraryId, text, source);
      setText("");
      setFiles([]);
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
    } catch (err) {
      onError(getUserFacingError(err, "Could not start the import"));
    } finally {
      setBusy(false);
    }
  };

  const show = async (job: ImportJob) => {
    try {
      setOpen(await liveSearchService.job(job.id));
    } catch (err) {
      onError(getUserFacingError(err, "Could not load the import report"));
    }
  };

  const hint = SOURCES.find((item) => item.value === source)?.hint;
  const isList = source === "ao3_bookmarks" || source === "ffn_favorites";

  return (
    <section className="live-import" aria-label="Import stories">
      <form onSubmit={start} className="live-import__form">
        <div className="discover-source-tabs" role="tablist" aria-label="Import source">
          {SOURCES.map((item) => (
            <button key={item.value} type="button" role="tab" aria-selected={item.value === source}
              className={item.value === source ? "is-active" : ""} onClick={() => setSource(item.value)}>{item.label}</button>
          ))}
        </div>
        <p className="discover-result-count">{hint}</p>
        {source === "epub" ? (
          <input type="file" accept=".epub,application/epub+zip" multiple aria-label="EPUB files"
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
        ) : isList ? (
          <input value={text} onChange={(event) => setText(event.target.value)} aria-label="User"
            placeholder={source === "ao3_bookmarks" ? "AO3 username" : "FanFiction.net user id"} />
        ) : (
          <textarea value={text} onChange={(event) => setText(event.target.value)} rows={6} aria-label="Links to import"
            placeholder="https://www.royalroad.com/fiction/…" />
        )}
        <button type="submit" className="discover-primary-btn"
          disabled={busy || (source === "epub" ? files.length === 0 : !text.trim())}>Start import</button>
      </form>

      {jobs.length > 0 && (
        <ul className="live-import__jobs" aria-label="Recent imports">
          {jobs.map((job) => (
            <li key={job.id}>
              <button type="button" onClick={() => void show(job)}>
                <strong>#{job.id} {SOURCES.find((item) => item.value === job.source)?.label ?? job.source}</strong>
                <span>{job.status} · {job.total_items} items · {Object.entries(job.counts).map(([key, value]) => `${value} ${key}`).join(", ")}</span>
                {job.error && <small>{job.error}</small>}
              </button>
              {ACTIVE.includes(job.status) && (
                <button type="button" className="discover-secondary-btn" onClick={() => void liveSearchService.cancel(job.id).then(refresh)}>Cancel</button>
              )}
            </li>
          ))}
        </ul>
      )}

      {open?.items && (
        <section className="live-import__report" aria-label={`Import ${open.id} report`}>
          <h3>Import #{open.id}</h3>
          <table>
            <thead><tr><th>#</th><th>Story</th><th>Result</th><th>Reason</th></tr></thead>
            <tbody>
              {open.items.map((item) => (
                <tr key={item.position} className={`is-${item.status}`}>
                  <td>{item.position + 1}</td>
                  <td>{item.title || item.label || item.url || "—"}</td>
                  <td>{item.status}</td>
                  <td>{item.reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </section>
  );
};

export default ImportJobsPanel;
