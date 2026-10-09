import React, { FormEvent, useEffect, useRef, useState } from "react";
import { Button, Dialog, Input } from "../ui";
import { useLibraryContext } from "../../context/useLibraryContext";

interface CreateLibraryModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/** "New library" dialog; the new library becomes the active one. */
const CreateLibraryModal: React.FC<CreateLibraryModalProps> = ({ isOpen, onClose }) => {
  const { createLibrary } = useLibraryContext();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      setName("");
      setError(null);
    }
  }, [isOpen]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await createLibrary(name.trim());
      onClose();
    } catch {
      setError("We couldn't create the library. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      title="New library"
      description="Libraries keep separate collections, for example one per reader or genre."
      initialFocus={inputRef}
      actions={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="create-library-form" variant="primary" loading={isSubmitting} disabled={!name.trim() || isSubmitting}>
            Create library
          </Button>
        </>
      }
    >
      <form id="create-library-form" onSubmit={handleSubmit}>
        <Input
          ref={inputRef}
          label="Library name"
          value={name}
          maxLength={120}
          onChange={(event) => setName(event.target.value)}
          placeholder="Space opera backlog"
          error={error ?? undefined}
          required
        />
      </form>
    </Dialog>
  );
};

export default CreateLibraryModal;
