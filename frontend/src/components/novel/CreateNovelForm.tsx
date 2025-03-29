import React, { FormEvent } from "react";
import { useState } from "react";
import { novelService } from "../../services/novelService";

interface NovelData {
  url: string;
  library_id: number;
}
interface CreateNovelProps {
  library_id: number;
}

const CreateNovelForm: React.FC<CreateNovelProps> = ({ library_id }) => {
  const [novelData, setNovelData] = useState<NovelData>({
    url: "",
    library_id: library_id,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<"success" | "error" | null>(
    null
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setNovelData((prev) => ({
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
      await novelService.addNovel(novelData.library_id, novelData.url);

      // Reset form and set success status
      setNovelData({ library_id: library_id, url: "" });
      setSubmitStatus("success");
    } catch (error) {
      console.error("Failed to create library:", error);
      setSubmitStatus("error");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="create-library-form">
      <h2>Add New Novel</h2>

      {submitStatus === "success" && (
        <div className="alert alert-success">Novel added successfully!</div>
      )}

      {submitStatus === "error" && (
        <div className="alert alert-error">
          Failed to add Novel. Please try again.
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="url">Novel url</label>
          <input
            type="text"
            id="url"
            name="url"
            value={novelData.url}
            onChange={handleInputChange}
            required
            disabled={isSubmitting}
          />
        </div>

        <button type="submit" disabled={isSubmitting || !novelData.url.trim()}>
          {isSubmitting ? "Creating..." : "Add Novel"}
        </button>
      </form>
    </div>
  );
};

export default CreateNovelForm;
