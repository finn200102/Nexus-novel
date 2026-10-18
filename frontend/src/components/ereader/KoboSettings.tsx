import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Copy, KeyRound, Trash2 } from "lucide-react";
import { useToast } from "../../context/useToast";
import { getUserFacingError } from "../../services/apiClient";
import { CreatedKoboDevice, KoboDevice, type KoboBookVersion, type KoboBookVersionPage, koboEndpointLine, koboService } from "../../services/koboService";
import { organizationService } from "../../services/organizationService";
import type { Shelf } from "../../types/organization";
import "../../styles/integrations.css";

import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";

const AUTO_SHELF = "";

const KoboSettingsContents: React.FC = () => {
  const generation = useRef(storageGeneration()).current, mounted = useRef(true);
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [books, setBooks] = useState<Record<number, KoboBookVersionPage>>({});
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [reviewBusy, setReviewBusy] = useState(false);
  const { addToast } = useToast();
  const [devices, setDevices] = useState<KoboDevice[]>([]);
  const [kepub, setKepub] = useState(false);
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [label, setLabel] = useState("");
  const [shelfChoice, setShelfChoice] = useState(AUTO_SHELF);
  const [created, setCreated] = useState<CreatedKoboDevice | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (!current()) return;
    try {
      const [list, shelfList] = await Promise.all([koboService.list(), organizationService.listShelves()]);
      if (!current()) return;
      setDevices(list.devices);
      setKepub(list.kepub);
      setShelves(shelfList);
    } catch (err) {
      if (current()) addToast(getUserFacingError(err, "Could not load Kobo devices"), "error");
    }
  };

  useEffect(() => {
    void load();
    // Loaded once when the section opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!current()) return;
    setBusy(true);
    try {
      const result = await koboService.create(label, shelfChoice === AUTO_SHELF ? null : Number(shelfChoice));
      if (!current()) return;
      setCreated(result);
      setLabel("");
      if (current()) await load();
    } catch (err) {
      if (current()) addToast(getUserFacingError(err, "Could not set up the Kobo"), "error");
    } finally {
      if (current()) setBusy(false);
    }
  };

  const changeShelf = async (device: KoboDevice, shelfId: number) => {
    if (!current()) return;
    try {
      await koboService.setShelf(device.id, shelfId);
      if (current()) await load();
    } catch (err) {
      if (current()) addToast(getUserFacingError(err, "Could not change the shelf"), "error");
    }
  };

  const revoke = async (device: KoboDevice) => {
    if (!current()) return;
    try {
      await koboService.revoke(device.id);
      if (current()) addToast(`Revoked "${device.label || "Kobo"}"`, "success");
      if (current()) await load();
    } catch (err) {
      if (current()) addToast(getUserFacingError(err, "Could not revoke the Kobo token"), "error");
    }
  };

  const copy = async (text: string) => {
    if (!current()) return;
    try {
      await navigator.clipboard.writeText(text);
      if (current()) addToast("Copied", "success");
    } catch {
      if (current()) addToast("Could not copy; select the text and copy it manually", "error");
    }
  };

  async function reviewBooks(deviceId: number, offset = 0) {
    if (!current()) return;
    setReviewBusy(true);
    try {
      const page = await koboService.books(deviceId, offset);
      if (!current()) return;
      setBooks(previous => ({ ...previous, [deviceId]: page })); setChecked({});
    } catch (err) { if (current()) addToast(getUserFacingError(err, "Could not review book versions"), "error"); }
    finally { if (current()) setReviewBusy(false); }
  }
  async function confirmBook(deviceId: number, book: KoboBookVersion) {
    if (!current() || !checked[book.entitlement_id]) return;
    setReviewBusy(true);
    try {
      await koboService.confirmVersion(deviceId, book.entitlement_id, {
        expected_fingerprint: book.fingerprint, expected_manifest_epoch: book.manifest_epoch,
        expected_manifest_revision: book.manifest_revision, reading_run_key: book.reading_run_key,
      });
      if (!current()) return;
      addToast("Installed version confirmed. New device bookmarks remain approximate.", "success");
      await reviewBooks(deviceId, books[deviceId]?.offset ?? 0);
    } catch (err) { if (current()) addToast(getUserFacingError(err, "The book changed. Sync the Kobo and review the installed version again."), "error"); }
    finally { if (current()) setReviewBusy(false); }
  }

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
            ? "KEPUB provides a more detailed device position. Device positions remain estimates and never mark source text as verified read."
            : "This server cannot convert to KEPUB (kepubify is missing), so books are sent as plain EPUB and the Kobo reports progress only per chapter."}
        </p>
      </div>

      <p className="account-form">After syncing or replacing a book, review its installed version below before device bookmarks can update Nexus. Book downloads alone do not confirm what is installed. Older bookmarks are kept for review; a new reading run requires a fresh book and confirmation.</p>

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
              </button>{" "}
              <button type="button" className="operations-action operations-action--quiet" disabled={reviewBusy} onClick={() => void reviewBooks(device.id)}>Review installed book versions</button>
              {books[device.id] && <section aria-label={`Installed book versions for ${device.label || "Kobo"}`}>
                {books[device.id].items.length === 0 && <p>No books have been advertised to this Kobo yet. Sync it first.</p>}
                {books[device.id].items.map(book => <div key={book.entitlement_id} className="account-form">
                  <strong>{book.title || "Untitled story"}</strong>
                  <p>{book.chapter_count} chapters · Generated {book.generated_at ? new Date(book.generated_at).toLocaleString() : "date unknown"}</p>
                  <p>{book.confirmed ? "Installed version confirmed. Incoming device positions are approximate." : "Version confirmation needed. Existing device bookmarks are preserved."}</p>
                  {!book.identity_known ? <p>This older book has no chapter identity proof. Sync a newly generated copy before confirming.</p> : <>
                    <label><input type="checkbox" checked={checked[book.entitlement_id] || false} disabled={reviewBusy}
                      onChange={event => setChecked(previous => ({ ...previous, [book.entitlement_id]: event.target.checked }))} />
                      I checked that this generated version is installed on {device.label || "my Kobo"}.</label>
                    <button type="button" disabled={reviewBusy || !checked[book.entitlement_id]} onClick={() => void confirmBook(device.id, book)}>Confirm installed version</button>
                  </>}
                </div>)}
                <p>{books[device.id].total} books · showing {books[device.id].offset + (books[device.id].items.length ? 1 : 0)}–{books[device.id].offset + books[device.id].items.length}</p>
                <button type="button" disabled={reviewBusy || books[device.id].offset === 0} onClick={() => void reviewBooks(device.id, Math.max(0, books[device.id].offset - 50))}>Previous books</button>
                <button type="button" disabled={reviewBusy || books[device.id].offset + books[device.id].items.length >= books[device.id].total} onClick={() => void reviewBooks(device.id, books[device.id].offset + 50)}>Next books</button>
              </section>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="account-form">No Kobo set up yet.</p>
      )}
    </article>
  );
};

const KoboSettings: React.FC = () => {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration, storageGeneration);
  return <KoboSettingsContents key={generation} />;
};
export default KoboSettings;
