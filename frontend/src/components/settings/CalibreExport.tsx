import React, { useState } from "react";
import { Download } from "lucide-react";
import { calibreService } from "../../services/calibreService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";

/** Downloads the user's EPUBs as a zip that Calibre can import. */
const CalibreExport: React.FC = () => {
  const { addToast } = useToast();
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    try {
      await calibreService.downloadExport();
      addToast("Your Calibre export is downloading", "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not prepare the Calibre export"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Calibre export">
      <p>Get your downloaded novels as EPUBs with tags, ratings and read state, ready to import into Calibre.</p>
      <button type="button" onClick={() => void download()} disabled={busy}>
        <Download size={14} aria-hidden="true" /> {busy ? "Preparing export…" : "Download for Calibre"}
      </button>
    </section>
  );
};

export default CalibreExport;
