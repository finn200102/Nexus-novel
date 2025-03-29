import React, { FormEvent } from "react";
import { useState } from "react";
import { libraryService } from "../../services/libraryService";
import "../../styles/library-form.css";

interface LibraryData {
  name: string;
}

const CreateLibraryForm: React.FC = () => {
  const [libraryData, setLibraryData] = useState<LibraryData>({
    name: "",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<"success" | "error" | null>(
    null
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setLibraryData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitStatus(null);

    try {
      // Create the library using the service
      await libraryService.createLibrary(libraryData.name);

      // Reset form and set success status
      setLibraryData({ name: "" });
      setSubmitStatus("success");
    } catch (error) {
      console.error("Failed to create library:", error);
      setSubmitStatus("error");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="library-form-container">
      <h2 className="form-title">Create New Library</h2>

      {submitStatus === "success" && (
        <div className="status-message success-message">
          Library created successfully!
        </div>
      )}

      {submitStatus === "error" && (
        <div className="status-message error-message">
          Failed to create library. Please try again.
        </div>
      )}

      <form className="library-form" onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="name" className="form-label">
            Library Name
          </label>
          <input
            type="text"
            id="name"
            name="name"
            value={libraryData.name}
            onChange={handleInputChange}
            required
            disabled={isSubmitting}
            className="form-input"
          />
        </div>

        <button
          type="submit"
          disabled={isSubmitting || !libraryData.name.trim()}
          className="submit-button"
        >
          {isSubmitting ? "Creating..." : "Create Library"}
        </button>
      </form>
    </div>
  );
};

export default CreateLibraryForm;
