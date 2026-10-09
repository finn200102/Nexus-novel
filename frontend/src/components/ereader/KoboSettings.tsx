import React, { useEffect, useState } from "react";
import { Copy, KeyRound, Trash2 } from "lucide-react";
import { useToast } from "../../context/useToast";
import { getUserFacingError } from "../../services/apiClient";
import { CreatedKoboDevice, KoboDevice, koboEndpointLine, koboService } from "../../services/koboService";
import { organizationService } from "../../services/organizationService";
import type { Shelf } from "../../types/organization";
import "../../styles/integrations.css";

const AUTO_SHELF = "";

const KoboSettings: React.FC = () => {
  const { addToast } = useToast();
  const [devices, setDevices] = useState<KoboDevice[]>([]);
  const [kepub, setKepub] = useState(false);
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [label, setLabel] = useState("");
  const [shelfChoice, setShelfChoice] = useState(AUTO_SHELF);
  const [created, setCreated] = useState<CreatedKoboDevice | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [list, shelfList] = await Promise.all([koboService.list(), organizationService.listShelves()]);
      setDevices(list.devices);
      setKepub(list.kepub);
      setShelves(shelfList);
    } catch (err) {
      addToast(getUserFacingError(err, "Could not load Kobo devices"), "error");
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
      const result = await koboService.create(label, shelfChoice === AUTO_SHELF ? null : Number(shelfChoice));
      setCreated(result);
      setLabel("");
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not set up the Kobo"), "error");
    } finally {
      setBusy(false);
    }
  };

  const changeShelf = async (device: KoboDevice, shelfId: number) => {
    try {
      await koboService.setShelf(device.id, shelfId);
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not change the shelf"), "error");
    }
  };

  const revoke = async (device: KoboDevice) => {
    try {
      await koboService.revoke(device.id);
      addToast(`Revoked "${device.label || "Kobo"}"`, "success");
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not revoke the Kobo token"), "error");
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

  const hasKoboShelf = shelves.some((shelf) => shelf.name === "Kobo");
  const createdLine = created ? koboEndpointLine(created.endpoint_path) : "";

  return (
    <article className="integrations-panel" aria-labelledby="kobo-sync-heading">
      <header>
        <div>
          <h2 id="kobo-sync-heading">Kobo</h2>
          <p>
            Sync a shelf and your reading progress straight to a Kobo e-reader, without KOReader.{" "}
            <strong>Experimental:</strong> this uses the same unofficial protocol as Calibre-Web and Komga and may
            break with Kobo firmware updates. Back up <code>Kobo eReader.conf</code> before editing it.
          </p>
        </div>
      </header>

      <div className="account-form">
        <ol>
          <li>Set up a device below and copy the <code>api_endpoint</code> line. It contains a secret token, shown once.</li>
          <li>
            Connect the Kobo by USB and open <code>.kobo/Kobo/Kobo eReader.conf</code> (a hidden folder). In the{" "}
            <code>[OneStoreServices]</code> section, replace the <code>api_endpoint=</code> line with the copied line.
          </li>
          <li>Eject the Kobo and tap Sync. Stories on the chosen shelf appear as books and in a collection with the shelf's name.</li>
          <li>Removing a story from the shelf removes it from the Kobo; deleting it on the Kobo takes it off the shelf.</li>
        </ol>
        <p>
          {kepub
            ? "Books are sent as KEPUB, so progress syncs to the exact place in a chapter. The furthest position wins."
            : "This server cannot convert to KEPUB (kepubify is missing), so books are sent as plain EPUB and the Kobo reports progress only per chapter."}
        </p>
      </div>

      {created && (
        <div className="account-form" role="status">
          <p>
            Put this line in <code>Kobo eReader.conf</code> for <strong>{created.label || "your Kobo"}</strong>. It is shown only once:
          </p>
          <code>{createdLine}</code>{" "}
          <button type="button" className="operations-action operations-action--quiet" onClick={() => void copy(createdLine)}>
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
          <input value={label} maxLength={120} placeholder="Kobo Clara" onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label>
          Shelf to sync
          <select value={shelfChoice} onChange={(event) => setShelfChoice(event.target.value)}>
            {!hasKoboShelf && <option value={AUTO_SHELF}>Kobo (new shelf)</option>}
            {shelves.map((shelf) => (
              <option key={shelf.id} value={hasKoboShelf && shelf.name === "Kobo" ? AUTO_SHELF : String(shelf.id)}>
                {shelf.name}
              </option>
            ))}
          </select>
        </label>
        <button className="operations-action" disabled={busy}>
          <KeyRound size={14} /> Set up Kobo
        </button>
      </form>

      {devices.length > 0 ? (
        <ul className="account-form">
          {devices.map((device) => (
            <li key={device.id}>
              {device.label || "Kobo"}
              {device.last_sync_at ? ` · last synced ${new Date(device.last_sync_at).toLocaleString()}` : " · not synced yet"}{" "}
              <label>
                <span className="sr-only">Shelf for {device.label || "Kobo"}</span>
                <select
                  value={device.shelf_id ?? ""}
                  onChange={(event) => void changeShelf(device, Number(event.target.value))}
                >
                  {device.shelf_id === null && <option value="">No shelf (nothing syncs)</option>}
                  {shelves.map((shelf) => (
                    <option key={shelf.id} value={shelf.id}>
                      {shelf.name}
                    </option>
                  ))}
                </select>
              </label>{" "}
              <button type="button" className="operations-action operations-action--quiet" onClick={() => void revoke(device)}>
                <Trash2 size={14} /> Revoke
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="account-form">No Kobo set up yet.</p>
      )}
    </article>
  );
};

export default KoboSettings;
