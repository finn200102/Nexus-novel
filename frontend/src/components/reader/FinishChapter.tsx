import { useEffect, useRef, useState } from "react";
import { readerToolsService } from "../../services/readerToolsService";
import { storageGeneration } from "../../services/accountStorage";
import type { ChapterIdentity } from "../../services/chapterIdentity";
import { Button } from "../ui";
import { useToast } from "../../context/useToast";
export default function FinishChapter({
  novelId,
  chapterNumber,
  version,
  runKey,
  identity,
  disabled,
}: {
  novelId: number;
  chapterNumber: number;
  version?: string | null;
  runKey: string | null;
  identity?: ChapterIdentity;
  disabled?: boolean;
}) {
  const [finished, setFinished] = useState(false);
  const [busy, setBusy] = useState(false),
    mounted = useRef(false),
    generation = storageGeneration();
  const { addToast } = useToast();
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const finish = async () => {
    if (busy || disabled || !identity || !version) return;
    setBusy(true);
    try {
      await readerToolsService.confirmRead(
        novelId,
        chapterNumber,
        version,
        runKey,
        identity,
      );
      if (mounted.current && generation === storageGeneration()) {
        setFinished(true);
        addToast(
          "This chapter is marked finished for the current text version.",
          "success",
        );
      }
    } catch {
      if (mounted.current && generation === storageGeneration())
        addToast(
          "Could not confirm this chapter. Reload its current text and try again.",
          "error",
        );
    } finally {
      if (mounted.current && generation === storageGeneration()) setBusy(false);
    }
  };
  return (
    <div className="reader-finish">
      <Button
        type="button"
        disabled={finished || busy || disabled || !identity || !version}
        onClick={() => void finish()}
      >
        {finished
          ? "Chapter finished"
          : busy
            ? "Saving…"
            : "I have finished this chapter"}
      </Button>
      {finished && (
        <p role="status">
          Finished for this text version in the current reading.
        </p>
      )}
      <p>
        Confirm only after reading this version. Moving to the next chapter does
        not confirm it.
      </p>
    </div>
  );
}
