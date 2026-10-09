import React, { useCallback, useEffect, useState } from "react";
import { getUserFacingError } from "../../services/apiClient";
import { ImportJob, liveSearchService } from "../../services/liveSearchService";
import { calibreService } from "../../services/calibreService";
import { Badge, Button, Input, Select, TextArea } from "../ui";
import { CalibreFileField } from "./CalibreFileField";

type Source = "url_list" | "rr_list" | "epub" | "calibre" | "ao3_bookmarks" | "ffn_favorites";

const SOURCES: Array<{ value: Source; label: string; hint: string }> = [
  { value: "url_list", label: "A list of links or a CSV file's text", hint: "Paste story links or a CSV export. Every link is added." },
  { value: "rr_list", label: "My Royal Road follows or favorites", hint: "Copy the text of your Royal Road follows or favorites page and paste it here." },
  { value: "epub", label: "EPUB files", hint: "EPUBs made by FanFicFare or FicHub include the story's link, so we can find it." },
  { value: "calibre", label: "Calibre library (metadata.db)", hint: "Pick metadata.db from your Calibre library folder. Stories are matched by their source links." },
  { value: "ao3_bookmarks", label: "AO3 bookmarks", hint: "Public bookmarks of an AO3 user." },
  { value: "ffn_favorites", label: "FanFiction.Net favorites", hint: "Public favorites of a FanFiction.Net profile. Enter the number from the profile link." },
];

const STATUS_LABELS: Record<string, string> = {
  queued: "Waiting",
  expanding: "Reading the list",
  running: "Adding stories",
  completed: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

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
      onError("Choose a library first.");
      return;
    }
    setBusy(true);
    try {
      let job: ImportJob;
      if (source === "epub") job = await liveSearchService.importEpubs(libraryId, files);
      else if (source === "calibre") job = await calibreService.importCalibre(libraryId, files[0]);
      else if (source === "ao3_bookmarks" || source === "ffn_favorites") job = await liveSearchService.importList(libraryId, source, text.trim());
      else job = await liveSearchService.importUrls(libraryId, text, source);
      setText("");
      setFiles([]);
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
    } catch (err) {
      onError(getUserFacingError(err, "Could not start the import."));
    } finally {
      setBusy(false);
    }
  };

  const show = async (job: ImportJob) => {
    try {
      setOpen(await liveSearchService.job(job.id));
    } catch (err) {
      onError(getUserFacingError(err, "Could not load the import report."));
    }
  };

  const current = SOURCES.find((item) => item.value === source);
  const isList = source === "ao3_bookmarks" || source === "ffn_favorites";

  return (
    <section className="add-import" aria-label="Import stories">
      <form onSubmit={start} className="add-import__form">
        <Select
          label="Import from"
          value={source}
          onChange={(event) => setSource(event.target.value as Source)}
          options={SOURCES.map((item) => ({ value: item.value, label: item.label }))}
        />
        {source === "calibre" ? <CalibreFileField onFiles={setFiles} /> : source === "epub" ? (
          <div className="ui-field">
            <label className="ui-field__label" htmlFor="add-import-files">EPUB files</label>
            <input
              id="add-import-files"
              className="add-import__file"
              type="file"
              accept=".epub,application/epub+zip"
              multiple
              aria-describedby="add-import-hint"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
            <p className="ui-field__hint" id="add-import-hint">{current?.hint}</p>
          </div>
        ) : isList ? (
          <Input
            label={source === "ao3_bookmarks" ? "AO3 username" : "FanFiction.Net user number"}
            hint={current?.hint}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        ) : (
          <TextArea
            label="Links or page text"
            hint={current?.hint}
            value={text}
            rows={6}
            onChange={(event) => setText(event.target.value)}
            placeholder="https://www.royalroad.com/fiction/…"
          />
        )}
        <Button type="submit" variant="primary" loading={busy}
          disabled={busy || (source === "epub" || source === "calibre" ? files.length === 0 : !text.trim())}>Start import</Button>
      </form>

      {jobs.length > 0 && (
        <section className="add-import__jobs" aria-labelledby="add-import-recent">
          <h3 id="add-import-recent" className="add-import__heading">Recent imports</h3>
          <ul>
            {jobs.map((job) => (
              <li key={job.id} className="add-import__job">
                <div className="add-import__job-text">
                  <strong>{SOURCES.find((item) => item.value === job.source)?.label ?? job.source}</strong>
                  <span className="text-secondary text-sm">
                    {job.total_items} {job.total_items === 1 ? "story" : "stories"}
                    {Object.entries(job.counts).map(([key, value]) => ` · ${value} ${key}`).join("")}
                  </span>
                  {job.error && <span className="text-sm add-import__error">{job.error}</span>}
                </div>
                <Badge tone={job.status === "failed" ? "danger" : job.status === "completed" ? "success" : "info"}>
                  {STATUS_LABELS[job.status] ?? job.status}
                </Badge>
                <div className="add-import__job-actions">
                  <Button size="sm" variant="ghost" onClick={() => void show(job)} aria-label={`Show report for import ${job.id}`}>Report</Button>
                  {ACTIVE.includes(job.status) && (
                    <Button size="sm" variant="secondary" onClick={() => void liveSearchService.cancel(job.id).then(refresh)}>Cancel</Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {open?.items && (
        <section className="add-import__report" aria-labelledby="add-import-report">
          <h3 id="add-import-report" className="add-import__heading">Import report</h3>
          <div className="add-import__table">
            <table>
              <thead><tr><th scope="col">#</th><th scope="col">Story</th><th scope="col">Result</th><th scope="col">Reason</th></tr></thead>
              <tbody>
                {open.items.map((item) => (
                  <tr key={item.position}>
                    <td>{item.position + 1}</td>
                    <td>{item.title || item.label || item.url || "–"}</td>
                    <td>{item.status}</td>
                    <td>{item.reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </section>
  );
};

export default ImportJobsPanel;
