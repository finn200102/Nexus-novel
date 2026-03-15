import React, { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authService } from "../../services/authService";
import "../../styles/auth-styles.css";

interface FormData {
  username: string;
  password: string;
}

const SignupForm: React.FC = () => {
  const [formData, setFormData] = useState<FormData>({
    username: "",
    password: "",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<"success" | "error" | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitStatus(null);

    try {
      await authService.register(formData);
      setSubmitStatus("success");
      setFormData({ username: "", password: "" });
      navigate("/");
    } catch {
      setSubmitStatus("error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prevData) => ({
      ...prevData,
      [name]: value,
    }));
  };

  return (
    <form className="signup-form" onSubmit={handleSubmit}>
      <div className="form-group">
        <label htmlFor="username" className="form-label">
          Username:
        </label>
        <input
          id="username"
          name="username"
          type="text"
          value={formData.username}
          onChange={handleChange}
          required
          className="form-input"
        />
      </div>

      <div className="form-group">
        <label htmlFor="password" className="form-label">
          Password:
        </label>
        <input
          id="password"
          name="password"
          type="password"
          value={formData.password}
          onChange={handleChange}
          required
          className="form-input"
        />
      </div>

      <button type="submit" disabled={isSubmitting} className="submit-button">
        {isSubmitting ? "Submitting..." : "Submit"}
      </button>

      {submitStatus === "success" && (
        <p className="status-message success">Signup successful!</p>
      )}
      {submitStatus === "error" && (
        <p className="status-message error">
          Error signing up. Please try again.
        </p>
      )}
    </form>
  );
};

export default SignupForm;
