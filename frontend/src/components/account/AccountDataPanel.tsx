import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Download, Upload } from "lucide-react";
import { useLibraryContext } from "../../context/useLibraryContext";
import { useToast } from "../../context/useToast";
import { getUserFacingError } from "../../services/apiClient";
import { userDataService, UserDataImportReport } from "../../services/userDataService";
import {onAccountStorageChange,storageGeneration} from "../../services/accountStorage";
import "../../styles/account-data.css";

const SUMMARY_LABELS: [string, string][] = [
  ["libraries_created", "Libraries created"],
  ["novels_created", "Stories added"],
  ["novels_linked", "Stories already in your library"],
  ["novels_failed", "Stories not imported"],
  ["novels_conflicts", "Private story destinations needing review"],
  ["follow_states_updated", "Follow states updated"],
  ["progress_applied", "Progress updated"],
  ["history_added", "History points added"],
  ["annotations_added", "Annotations added"],
  ["annotations_deferred", "Annotations waiting for chapters"],
  ["saved_searches_created", "Saved searches added"],
  ["saved_searches_conflicts", "Saved search name conflicts"],
  ["smart_shelves_created", "Private smart shelves added"],
  ["smart_shelves_conflicts", "Smart shelf name conflicts"],
];

const AccountDataContents: React.FC = () => {
  const generation=storageGeneration(),mounted=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const current=()=>mounted.current&&generation===storageGeneration();
  const { addToast } = useToast();
  const { refreshLibraries, libraries } = useLibraryContext();
  const fileInput = useRef<HTMLInputElement>(null);
  const backupInput = useRef<HTMLInputElement>(null);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [exportingBackup, setExportingBackup] = useState(false);
  const [importingBackup, setImportingBackup] = useState(false);
  const [backupLibrary,setBackupLibrary]=useState("");
  const [report, setReport] = useState<UserDataImportReport | null>(null);

  const exportData = async () => {
    setExporting(true);
    try {
      const payload = await userDataService.exportData();
      if(!current())return;
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
      if(!current())return;
      addToast(getUserFacingError(err, "Could not export your data"), "error");
    } finally {
      if(current())setExporting(false);
    }
  };

  const exportFullBackup = async () => {
    setExportingBackup(true);
    try {
      const payload=await userDataService.exportFullBackup(backupLibrary||undefined);
      if(!current())return;
      const url=URL.createObjectURL(payload),link=document.createElement("a");
      link.href=url;link.download=`nexus-full-backup-${new Date().toISOString().slice(0,10)}.zip`;
      document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
      addToast("Your full backup is downloading", "success");
    } catch(err) {
      if(!current())return;
      addToast(getUserFacingError(err,"Could not export your full backup"),"error");
    } finally { if(current())setExportingBackup(false); }
  };

  const importFullBackup = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file=event.target.files?.[0];event.target.value="";if(!file)return;
    setImportingBackup(true);setReport(null);
    try {
      const result=await userDataService.importFullBackup(file);
      if(!current())return;
      setReport(result);await refreshLibraries();if(!current())return;
      addToast("Backup imported. Review chapter matches and choose which archived bodies to restore.","success");
    } catch(err) {
      if(!current())return;
      addToast(getUserFacingError(err,"Could not import this full backup"),"error");
    } finally { if(current())setImportingBackup(false); }
  };

  const importFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImporting(true);
    setReport(null);
    try {
      const text=await file.text();
      if(!current())return;
      const payload: unknown = JSON.parse(text);
      const result = await userDataService.importData(payload);
      if(!current())return;
      setReport(result);
      await refreshLibraries();
      if(!current())return;
      addToast("Import finished", "success");
    } catch (err) {
      if(!current())return;
      if (err instanceof SyntaxError) {
        addToast("That file is not a Nexus data export", "error");
      } else {
        addToast(getUserFacingError(err, "Could not import this file"), "error");
      }
    } finally {
      if(current())setImporting(false);
    }
  };

  const failedNovels = report?.libraries.flatMap((library) =>
    library.novels.filter((novel) => novel.status === "failed" || novel.status === "conflict").map((novel) => ({ library: library.name, novel }))
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
          Account data JSON contains libraries, progress, notes, annotations and organization settings. A full backup ZIP adds owned chapter text and retained chapter versions; it excludes generated audio, voice profiles, provider credentials, and source files the app did not retain.
          Backup chapter bodies stay staged in your private review until you explicitly restore them into empty chapters. Existing chapter text is never replaced.
        </p>
        <div className="account-data__actions">
          <button type="button" onClick={() => void exportData()} disabled={exporting}>
            <Download size={14} aria-hidden="true" /> {exporting ? "Preparing export…" : "Export account data (.json)"}
          </button>
          <button type="button" onClick={() => fileInput.current?.click()} disabled={importing}>
            <Upload size={14} aria-hidden="true" /> {importing ? "Importing…" : "Import account data (.json)"}
          </button>
          <button type="button" onClick={() => void exportFullBackup()} disabled={exportingBackup}>
            <Download size={14} aria-hidden="true" /> {exportingBackup ? "Preparing backup…" : "Export full backup (.zip)"}
          </button>
          <button type="button" onClick={() => backupInput.current?.click()} disabled={importingBackup}>
            <Upload size={14} aria-hidden="true" /> {importingBackup ? "Importing backup…" : "Import full backup (.zip)"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            aria-label="Nexus data export file"
            onChange={(event) => void importFile(event)}
          />
          <input ref={backupInput} type="file" accept="application/zip,.zip" hidden aria-label="Nexus full backup archive" onChange={(event)=>void importFullBackup(event)} />
        </div>
        <label className="account-data__backup-scope">Full backup scope
          <select value={backupLibrary} onChange={event=>setBackupLibrary(event.target.value)} disabled={exportingBackup||importingBackup}>
            <option value="">All libraries</option>
            {(libraries||[]).map(library=><option key={library.id} value={library.name}>{library.name}</option>)}
          </select>
        </label>

        {report && (
          <div className="account-data__report" role="status">
            {report.reader_preferences && <p>{report.reader_preferences === "applied" ? "Reader settings imported." : report.reader_preferences === "kept_local" ? "Your existing reader settings differ; kept your current choices." : "Reader settings already match this export."}</p>}
            {report.discovery_preferences && <p>{report.discovery_preferences === "applied" ? "Discovery preferences imported." : report.discovery_preferences === "kept_local" ? "Kept your different current discovery preferences." : "Discovery preferences already match this export."}</p>}
            {(report.smart_shelves ?? []).filter(item => item.status === "conflict" || item.status === "invalid" || item.status === "limit_reached" || item.needs_review).map(item => <p key={`smart:${item.name}`}>
              {item.status === "conflict" ? `Smart shelf “${item.name}” already has different criteria; kept your version.` : item.status === "limit_reached" ? `Smart shelf “${item.name}” was not added because this account has reached its smart shelf limit.` : item.status === "invalid" ? `Smart shelf “${item.name}” could not be imported. Review its name and criteria.` : `Smart shelf “${item.name}” is paused for review. Open Smart shelves from your library’s Organize menu and choose its intended libraries and filters.`}
            </p>)}
            {report.libraries.flatMap(library => library.novels.filter(novel => novel.reader_preferences === "kept_local").map(novel => <p key={`${library.name}:${novel.novel_id??novel.portable_link_id??novel.url??novel.title}`}>Kept your current text settings for {novel.title || novel.url}.</p>))}
            {report.libraries.some(library=>library.novels.some(novel=>novel.reading_review_id))&&<p>Imported chapter references are retained. Open “Imported reading places and annotations” below to review their matches.</p>}
            {report.libraries.flatMap(library=>library.novels.filter(novel=>novel.original_status==='unavailable'||novel.original_status==='backup_review').map(novel=><p key={`original:${novel.novel_id??novel.portable_link_id}`}>{novel.original_status==='backup_review'?`“${novel.title||'Private story'}” has archived chapter text staged in its private review. Choose chapter matches and the restore option below to finish.`:`“${novel.title||'Private story'}” is retained in ${library.name}. Its original content is unavailable here. Restore the original separately, then review its chapter matches; nothing is fetched automatically.`}</p>))}
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
                  <li key={`${library}:${novel.novel_id??novel.portable_link_id??novel.url??novel.title}`}>
                    {novel.title||novel.url||"Private original"} ({library}): {novel.reason ?? "not imported"}
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

export default function AccountDataPanel(){const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration);return <AccountDataContents key={generation}/>;}
