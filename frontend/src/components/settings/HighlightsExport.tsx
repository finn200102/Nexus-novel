import React, { useEffect, useState } from "react";
import { highlightsExportService } from "../../services/highlightsExportService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { Banner, Button } from "../ui";

const HighlightsExport: React.FC = () => {
  const { addToast } = useToast();
  const [connected, setConnected] = useState<boolean | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<"zip" | "connect" | "sync" | "disconnect" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    highlightsExportService
      .readwiseStatus()
      .then((status) => setConnected(status.connected))
      .catch(() => setConnected(false));
  }, []);

  const run = async (kind: "zip" | "connect" | "sync" | "disconnect", task: () => Promise<void>, failure: string) => {
    setBusy(kind);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(getUserFacingError(err, failure));
    } finally {
      setBusy(null);
    }
  };

  const downloadZip = () =>
    run("zip", () => highlightsExportService.downloadLibraryZip(), "Could not prepare the highlights export.");

  const connect = () =>
    run(
      "connect",
      async () => {
        const status = await highlightsExportService.connectReadwise(token.trim());
        setConnected(status.connected);
        setToken("");
        addToast("Readwise connected.", "success");
      },
      "Readwise did not accept this token.",
    );

  const sync = () =>
    run(
      "sync",
      async () => {
        const result = await highlightsExportService.syncReadwise();
        addToast(result.exported ? `Sent ${result.exported} highlights to Readwise.` : "Readwise is already up to date.", "success");
      },
      "Readwise sync failed. Try again later.",
    );

  const disconnect = () =>
    run(
      "disconnect",
      async () => {
        await highlightsExportService.disconnectReadwise();
        setConnected(false);
        addToast("Readwise disconnected.", "success");
      },
      "Could not disconnect Readwise.",
    );

  return (
    <section className="settings-group" aria-labelledby="settings-highlights-export">
      <h2 id="settings-highlights-export">Highlights</h2>
      <p className="settings-group__hint">Export your highlights and private notes as Markdown, one file per story.</p>
      <div>
        <Button onClick={() => void downloadZip()} loading={busy === "zip"} disabled={busy !== null}>
          Download Markdown zip
        </Button>
      </div>

      <h3>Readwise</h3>
      {connected === null ? null : connected ? (
        <>
          <p className="settings-group__hint">Connected. Only highlights not yet sent are pushed.</p>
          <div>
            <Button onClick={() => void sync()} loading={busy === "sync"} disabled={busy !== null}>
              Sync now
            </Button>{" "}
            <Button variant="ghost" onClick={() => void disconnect()} loading={busy === "disconnect"} disabled={busy !== null}>
              Disconnect
            </Button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (token.trim()) void connect();
          }}
        >
          <label htmlFor="readwise-token">Readwise access token</label>
          <input
            id="readwise-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <p className="settings-group__hint">Create a token at readwise.io/access_token.</p>
          <Button type="submit" loading={busy === "connect"} disabled={busy !== null || !token.trim()}>
            Test and connect
          </Button>
        </form>
      )}
      {error && <Banner tone="danger">{error}</Banner>}
    </section>
  );
};

export default HighlightsExport;
