import { useEffect, useState } from "react";
import apiClient, { getUserFacingError } from "../../services/apiClient";
import "../../styles/integrations.css";

interface Manifest { id: string; name: string; version: string; publisher: string; allowed_hosts: string[]; asset_hosts?: string[]; capabilities: string[]; limitations: string[] }
interface Installation { id: string; name: string; enabled: boolean; pinned_digest: string; manifest: Manifest; last_error: string | null }
interface Preview { manifest: Manifest; digest: string; canaries: { fixture: string; records: number; passed: boolean }[] }
interface Version { version: string; digest: string }
interface RegistryEntry extends Version { id: string; name: string; publisher: string }
const endpoint = "/admin/integrations/plugins";

export default function SourcePlugins() {
  const [installed, setInstalled] = useState<Installation[]>([]);
  const [versions, setVersions] = useState<Record<string, Version[]>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [payload, setPayload] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [url, setUrl] = useState<Record<string, string>>({});
  const [registry, setRegistry] = useState<RegistryEntry[] | null>(null);
  const load = async () => setInstalled((await apiClient.get<Installation[]>(endpoint)).data);
  useEffect(() => { void load().catch(err => setError(getUserFacingError(err, "Source packages are unavailable."))); }, []);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (err) { setError(getUserFacingError(err, "The source package could not be updated.")); }
    finally { setBusy(false); }
  }
  async function select(file: File | undefined) {
    setPreview(null); setPayload(null);
    if (!file) return;
    if (file.size > 8_000_000) { setError("Choose a source package smaller than 8 MB."); return; }
    await run(async () => {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let start = 0; start < bytes.length; start += 8192) binary += String.fromCharCode(...bytes.subarray(start, start + 8192));
      const data_base64 = btoa(binary);
      const response = await apiClient.post<Preview>(`${endpoint}/preview`, { data_base64 }, { timeout: 60_000 });
      setPreview(response.data); setPayload(data_base64);
    });
  }
  async function action(id: string, value: string, digest?: string) {
    await run(async () => {
      await apiClient.post(`${endpoint}/${id}/actions`, { action: value, digest }, { timeout: 60_000 });
      setMessage(value === "test" ? "Fixture checks passed." : "Source package updated."); await load();
    });
  }
  return <div className="integrations-page">
    <header className="integrations-page__header"><div><h2>Source packages</h2><p>Install reviewed source adapters and keep each one pinned to a tested version. Updates are manual.</p></div></header>
    {error && <p role="alert" className="integrations-alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <section className="integrations-panel"><h3>Curated registry</h3>
      <button className="operations-action" disabled={busy} onClick={() => void run(async () => {
        const response = await apiClient.get<{ configured: boolean; index: { entries: RegistryEntry[] } | null }>(`${endpoint}/registry`);
        setRegistry(response.data.index?.entries ?? []);
        if (!response.data.configured) setMessage("No source registry is configured. You can preview a signed package below.");
      })}>Check registry</button>
      {registry?.map(entry => <p key={`${entry.id}:${entry.version}`}>{entry.name} · {entry.version} · {entry.publisher} <button className="operations-action" disabled={busy} onClick={() => void run(async () => {
        setPreview(null); setPayload(null);
        const response = await apiClient.post<Preview & { data_base64: string }>(`${endpoint}/registry/${entry.id}/${entry.version}/preview`, { digest: entry.digest }, { timeout: 90_000 });
        setPreview(response.data); setPayload(response.data.data_base64);
      })}>Preview this version</button></p>)}
    </section>
    <section className="integrations-panel" aria-label="Install a source package">
      <label>Signed source package <input type="file" accept=".zip" disabled={busy} onChange={event => void select(event.target.files?.[0])} /></label>
      <p>Trusted publishers are configured by the administrator on the server. Every package runs its included fixture checks before installation.</p>
      {preview && <div><h3>{preview.manifest.name} · {preview.manifest.version}</h3>
        <p>Publisher: {preview.manifest.publisher}. Sources: {preview.manifest.allowed_hosts.join(", ")}. Supports: {preview.manifest.capabilities.join(", ")}.</p>
        {!!preview.manifest.asset_hosts?.length && <p>Additional illustration hosts: {preview.manifest.asset_hosts.join(", ")}. These hosts supply images only.</p>}
        {preview.manifest.limitations.map(item => <p key={item}>{item}</p>)}
        <p>{preview.canaries.length} fixture checks passed.</p>
        <button className="operations-action" disabled={busy || !payload} onClick={() => void run(async () => {
          await apiClient.post(`${endpoint}/install`, { data_base64: payload, enable: true }, { timeout: 60_000 });
          setPreview(null); setPayload(null); setMessage("Source package installed."); await load();
        })}>Install this version</button></div>}
    </section>
    {installed.length === 0 && <p>No source packages installed. Built-in sources remain available.</p>}
    {installed.map(item => <section className="integrations-panel" key={item.id}>
      <h3>{item.name} · {item.manifest.version}</h3><p>{item.enabled ? "Enabled" : "Disabled"} · {item.manifest.allowed_hosts.join(", ")}</p>
      {!!item.manifest.asset_hosts?.length && <p>Illustration hosts: {item.manifest.asset_hosts.join(", ")}</p>}
      <p>{item.manifest.capabilities.join(", ")}</p>{item.manifest.limitations.map(limit => <p key={limit}>{limit}</p>)}
      {item.last_error && <p role="alert">{item.last_error}</p>}
      <div className="integration-actions">
        <button className="operations-action" disabled={busy} onClick={() => void action(item.id, item.enabled ? "disable" : "enable")}>{item.enabled ? "Disable" : "Enable"}</button>
        <button className="operations-action" disabled={busy} onClick={() => void action(item.id, "test")}>Test fixtures</button>
        <button className="operations-action" disabled={busy} onClick={() => void run(async () => { const response = await apiClient.get<Version[]>(`${endpoint}/${item.id}/versions`); setVersions(current => ({ ...current, [item.id]: response.data })); })}>Versions</button>
      </div>
      {versions[item.id]?.map(version => <p key={version.digest}>{version.version} {version.digest === item.pinned_digest ? "· Current" : <button className="operations-action" disabled={busy} onClick={() => void action(item.id, "rollback", version.digest)}>Restore this version</button>}</p>)}
      <form onSubmit={event => { event.preventDefault(); void run(async () => {
        const response = await apiClient.post<{ records: { title: string }[] }>(`${endpoint}/${item.id}/diagnostic`, { url: url[item.id], operation: "metadata" }, { timeout: 90_000 });
        setMessage(`Live check returned ${response.data.records.length} work record(s): ${response.data.records.map(record => record.title).join(", ")}`);
      }); }}>
        <label>Check one live work page <input type="url" required disabled={busy || !item.enabled} value={url[item.id] ?? ""} onChange={event => setUrl(current => ({ ...current, [item.id]: event.target.value }))} /></label>
        <button className="operations-action" disabled={busy || !item.enabled || !item.manifest.capabilities.includes("metadata")}>Check page</button>
      </form>
    </section>)}
  </div>;
}
