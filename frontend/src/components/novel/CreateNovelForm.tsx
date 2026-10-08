import React, { FormEvent, useEffect, useState } from "react";
import axios from "axios";
import { novelService } from "../../services/novelService";
import { useToast } from "../../context/useToast";
import "../../styles/novel-form.css";

interface CreateNovelProps {
  library_id: number;
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

type DrawerMode = "single" | "batch";

const CreateNovelForm: React.FC<CreateNovelProps> = ({
  library_id,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [mode, setMode] = useState<DrawerMode>("single");
  const [urlInput, setUrlInput] = useState("");
  const [batchInput, setBatchInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { addToast } = useToast();

  useEffect(() => {
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    if (isOpen) {
      document.addEventListener("keydown", handleKeydown);
    }
    return () => document.removeEventListener("keydown", handleKeydown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) {
      setUrlInput("");
      setBatchInput("");
      setMode("single");
    }
  }, [isOpen, library_id]);

  if (!isOpen) {
    return null;
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      if (mode === "single") {
        await novelService.addNovel(library_id, urlInput.trim());
      } else {
        const urls = batchInput
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        if (urls.length === 0) {
          throw new Error("Please provide at least one URL");
        }
        await novelService.addNovels(library_id, urls);
      }

      addToast("Novels queued for download.", "success");
      onSuccess?.();
      if (mode === "single") {
        setUrlInput("");
      } else {
        setBatchInput("");
      }
    } catch (error) {
      console.error("Failed to add novel", error);
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
      if (detail === "Novel already exists") {
        addToast("This novel is already in your library.", "success");
        onSuccess?.();
      } else {
        addToast(detail || "Something went wrong. Please try again.", "error");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="novel-drawer" role="dialog" aria-modal="true">
      <div className="novel-drawer__overlay" onClick={onClose} />
      <div className="novel-drawer__panel">
        <header className="novel-drawer__header">
          <div>
            <p>Add novels</p>
            <h2>Import by URL</h2>
          </div>
          <button type="button" className="novel-drawer__close" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="novel-drawer__tabs">
          <button
            type="button"
            className={mode === "single" ? "is-active" : ""}
            onClick={() => setMode("single")}
          >
            Single URL
          </button>
          <button
            type="button"
            className={mode === "batch" ? "is-active" : ""}
            onClick={() => setMode("batch")}
          >
            Multiple URLs
          </button>
        </div>

        <form className="novel-drawer__form" onSubmit={handleSubmit}>
          {mode === "single" ? (
            <div className="novel-drawer__group">
              <label htmlFor="novel-url">Novel URL</label>
              <input
                id="novel-url"
                type="url"
                placeholder="https://www.royalroad.com/fiction/..."
                value={urlInput}
                onChange={(event) => setUrlInput(event.target.value)}
                required
                disabled={isSubmitting}
              />
            </div>
          ) : (
            <div className="novel-drawer__group">
              <label htmlFor="novel-batch">One URL per line</label>
              <textarea
                id="novel-batch"
                rows={6}
                placeholder="https://...
https://..."
                value={batchInput}
                onChange={(event) => setBatchInput(event.target.value)}
                disabled={isSubmitting}
              />
            </div>
          )}

          <button
            type="submit"
            className="novel-drawer__submit"
            disabled={
              isSubmitting ||
              (mode === "single" ? !urlInput.trim() : !batchInput.trim())
            }
          >
            {isSubmitting ? "Adding..." : "Add to library"}
          </button>
        </form>
      </div>
    </div>
  );
};

export default CreateNovelForm;
