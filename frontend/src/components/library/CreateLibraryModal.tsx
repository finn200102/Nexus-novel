import React, { FormEvent, useEffect, useState } from "react";
import { useLibraryContext } from "../../context/useLibraryContext";
import "../../styles/library-form.css";

interface CreateLibraryModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const CreateLibraryModal: React.FC<CreateLibraryModalProps> = ({
  isOpen,
  onClose,
}) => {
  const { createLibrary } = useLibraryContext();
  const [name, setName] = useState("");
  const [accent, setAccent] = useState("indigo");
  const [status, setStatus] = useState<"success" | "error" | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      setName("");
      setAccent("indigo");
      setStatus(null);
    }
  }, [isOpen]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    if (isOpen) {
      document.addEventListener("keydown", handler);
    }
    return () => document.removeEventListener("keydown", handler);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setStatus(null);
    try {
      await createLibrary(name.trim());
      setStatus("success");
      onClose();
    } catch (err) {
      console.error("Failed to create library", err);
      setStatus("error");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="library-modal" role="dialog" aria-modal="true">
      <div className="library-modal__overlay" onClick={onClose} />
      <div className="library-modal__panel">
        <header className="library-modal__header">
          <div>
            <p>Create Library</p>
            <h2>Name your new collection</h2>
          </div>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <form className="library-modal__form" onSubmit={handleSubmit}>
          <label>
            Library name
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Space Opera backlog"
              required
              disabled={isSubmitting}
            />
          </label>
          <div className="library-modal__palette">
            {accentColors.map((color) => (
              <button
                type="button"
                key={color.value}
                className={accent === color.value ? "is-active" : ""}
                style={{ background: color.swatch }}
                onClick={() => setAccent(color.value)}
              >
                <span>{color.label}</span>
              </button>
            ))}
          </div>
          {status === "error" && (
            <p className="library-modal__status">Something went wrong. Try again.</p>
          )}
          <button
            type="submit"
            disabled={!name.trim() || isSubmitting}
            className="library-modal__submit"
          >
            {isSubmitting ? "Creating…" : "Create library"}
          </button>
        </form>
      </div>
    </div>
  );
};

const accentColors = [
  { value: "indigo", label: "Indigo", swatch: "linear-gradient(135deg,#818cf8,#4338ca)" },
  { value: "amber", label: "Amber", swatch: "linear-gradient(135deg,#fbbf24,#f97316)" },
  { value: "emerald", label: "Emerald", swatch: "linear-gradient(135deg,#34d399,#059669)" },
];

export default CreateLibraryModal;
