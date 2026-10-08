import React, { useEffect, useState } from "react";
import { Copy, KeyRound, Trash2 } from "lucide-react";
import { useToast } from "../../context/useToast";
import { getUserFacingError } from "../../services/apiClient";
import { AppPassword, AppPasswordScope, CreatedAppPassword, ereaderService } from "../../services/ereaderService";
import "../../styles/integrations.css";

const SCOPE_LABELS: Record<AppPasswordScope, string> = {
  opds: "Books (OPDS catalog)",
  kosync: "Reading progress (KOReader sync)",
};

const apiUrl = (path: string) => `${window.location.origin}/api${path}`;

const EReaderSettings: React.FC = () => {
  const { addToast } = useToast();
  const [passwords, setPasswords] = useState<AppPassword[]>([]);
  const [label, setLabel] = useState("");
  const [scope, setScope] = useState<AppPasswordScope>("opds");
  const [created, setCreated] = useState<CreatedAppPassword | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setPasswords(await ereaderService.list());
    } catch (err) {
      addToast(getUserFacingError(err, "Could not load app passwords"), "error");
    }
  };

  useEffect(() => {
    void load();
    // Loaded once when the section opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await ereaderService.create(label, scope);
      setCreated(result);
      setLabel("");
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not create the app password"), "error");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (item: AppPassword) => {
    try {
      await ereaderService.revoke(item.id);
      addToast(`Revoked "${item.label || item.scope}"`, "success");
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not revoke the app password"), "error");
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      addToast("Copied", "success");
    } catch {
      addToast("Could not copy; select the text and copy it manually", "error");
    }
  };

  const opdsUrl = apiUrl("/opds/");
  const kosyncUrl = apiUrl("/kosync");
  const active = passwords.filter((item) => !item.revoked_at);

  return (
    <article className="integrations-panel">
      <header>
        <div>
          <h2>E-readers</h2>
          <p>
            Read your followed stories on KOReader, Kobo, Moon+ Reader or Thorium. Use an app password for
            the device, never your account password.
          </p>
        </div>
      </header>

      <div className="account-form">
        <p>
          <strong>Catalog (OPDS) URL:</strong> <code>{opdsUrl}</code>{" "}
          <button type="button" className="operations-action operations-action--quiet" onClick={() => void copy(opdsUrl)}>
            <Copy size={14} /> Copy
          </button>
        </p>
        <p>
          <strong>Progress sync (KOReader) URL:</strong> <code>{kosyncUrl}</code>{" "}
          <button type="button" className="operations-action operations-action--quiet" onClick={() => void copy(kosyncUrl)}>
            <Copy size={14} /> Copy
          </button>
        </p>
        <ol>
          <li>In KOReader, open the OPDS catalog browser and add a catalog with the URL above, your username and an app password with the books scope.</li>
          <li>In KOReader, open Tools, Progress sync, and set the custom sync server to the URL above with the same username. Enter the app password with the progress scope as the password.</li>
          <li>After new chapters are downloaded, download the book again from the catalog to get them.</li>
        </ol>
      </div>

      {created && (
        <div className="account-form" role="status">
          <p>
            New app password for <strong>{created.label || SCOPE_LABELS[created.scope]}</strong>. It is shown only once:
          </p>
          <code>{created.secret}</code>{" "}
          <button type="button" className="operations-action operations-action--quiet" onClick={() => void copy(created.secret)}>
            <Copy size={14} /> Copy
          </button>{" "}
          <button type="button" className="operations-action operations-action--quiet" onClick={() => setCreated(null)}>
            Done
          </button>
        </div>
      )}

      <form className="account-form" onSubmit={create}>
        <label>
          Device name
          <input value={label} maxLength={120} placeholder="Kobo Libra" onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label>
          Use for
          <select value={scope} onChange={(event) => setScope(event.target.value as AppPasswordScope)}>
            <option value="opds">{SCOPE_LABELS.opds}</option>
            <option value="kosync">{SCOPE_LABELS.kosync}</option>
          </select>
        </label>
        <button className="operations-action" disabled={busy}>
          <KeyRound size={14} /> Create app password
        </button>
      </form>

      {active.length > 0 ? (
        <ul className="account-form">
          {active.map((item) => (
            <li key={item.id}>
              {item.label || "Unnamed device"} · {SCOPE_LABELS[item.scope]}
              {item.last_used_at ? ` · last used ${new Date(item.last_used_at).toLocaleDateString()}` : ""}{" "}
              <button type="button" className="operations-action operations-action--quiet" onClick={() => void revoke(item)}>
                <Trash2 size={14} /> Revoke
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="account-form">No app passwords yet.</p>
      )}
    </article>
  );
};

export default EReaderSettings;
