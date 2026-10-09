import React, { useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { useLibraryContext } from "../../context/useLibraryContext";
import { useToast } from "../../context/useToast";
import { getUserFacingError } from "../../services/apiClient";
import { userDataService, UserDataImportReport } from "../../services/userDataService";
import "../../styles/account-data.css";

const SUMMARY_LABELS: [string, string][] = [
  ["libraries_created", "Libraries created"],
  ["novels_created", "Stories added"],
  ["novels_linked", "Stories already in your library"],
  ["novels_failed", "Stories not imported"],
  ["follow_states_updated", "Follow states updated"],
  ["progress_applied", "Progress updated"],
  ["history_added", "History points added"],
  ["annotations_added", "Annotations added"],
  ["annotations_deferred", "Annotations waiting for chapters"],
  ["saved_searches_created", "Saved searches added"],
  ["saved_searches_conflicts", "Saved search name conflicts"],
];

const AccountDataPanel: React.FC = () => {
  const { addToast } = useToast();
  const { refreshLibraries } = useLibraryContext();
  const fileInput = useRef<HTMLInputElement>(null);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [report, setReport] = useState<UserDataImportReport | null>(null);

  const exportData = async () => {
    setExporting(true);
    try {
      const payload = await userDataService.exportData();
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `nexus-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      addToast("Your data export is downloading", "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not export your data"), "error");
    } finally {
      setExporting(false);
    }
  };

  const importFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImporting(true);
    setReport(null);
    try {
      const payload: unknown = JSON.parse(await file.text());
      const result = await userDataService.importData(payload);
      setReport(result);
      await refreshLibraries();
      addToast("Import finished", "success");
    } catch (err) {
      if (err instanceof SyntaxError) {
        addToast("That file is not a Nexus data export", "error");
      } else {
        addToast(getUserFacingError(err, "Could not import this file"), "error");
      }
    } finally {
      setImporting(false);
    }
  };

  const failedNovels = report?.libraries.flatMap((library) =>
    library.novels.filter((novel) => novel.status === "failed").map((novel) => ({ library: library.name, novel }))
  ) ?? [];
  const conflicts = report?.saved_searches.filter((item) => item.status === "conflict") ?? [];

  return (
    <section className="dashboard-panel account-data" aria-labelledby="account-data-title">
      <header className="dashboard-panel__header">
        <div>
          <p>Your data</p>
          <h2 id="account-data-title">Account data</h2>
        </div>
      </header>
      <div className="account-data__body">
        <p>
          Export your libraries, follow states, progress, history, annotations and saved searches as one JSON file.
          Stories are matched by their link, so importing the file again re-links them and changes nothing that is already there.
        </p>
        <div className="account-data__actions">
          <button type="button" onClick={() => void exportData()} disabled={exporting}>
            <Download size={14} aria-hidden="true" /> {exporting ? "Preparing export…" : "Export my data"}
          </button>
          <button type="button" onClick={() => fileInput.current?.click()} disabled={importing}>
            <Upload size={14} aria-hidden="true" /> {importing ? "Importing…" : "Import data"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            aria-label="Nexus data export file"
            onChange={(event) => void importFile(event)}
          />
        </div>

        {report && (
          <div className="account-data__report" role="status">
            <dl className="account-data__summary">
              {SUMMARY_LABELS.map(([key, label]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>{report.summary[key] ?? 0}</dd>
                </div>
              ))}
            </dl>
            {failedNovels.length > 0 && (
              <ul className="account-data__problems">
                {failedNovels.map(({ library, novel }) => (
                  <li key={`${library}:${novel.url}`}>
                    {novel.url} ({library}): {novel.reason ?? "not imported"}
                  </li>
                ))}
              </ul>
            )}
            {conflicts.length > 0 && (
              <ul className="account-data__problems">
                {conflicts.map((item) => (
                  <li key={item.name}>Saved search "{item.name}" already exists with different filters; kept your version.</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
};

export default AccountDataPanel;
