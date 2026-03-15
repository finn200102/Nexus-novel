import React, { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { authService } from "../../services/authService";
import "../../styles/auth-styles.css";

interface FormData {
  username: string;
  password: string;
}

const LoginForm: React.FC = () => {
  const [formData, setFormData] = useState<FormData>({
    username: "",
    password: "",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<"success" | "error" | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const navigate = useNavigate();

  useEffect(() => {
    if (authService.isAuthenticated()) {
      navigate("/");
    }
  }, [navigate]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitStatus(null);
    setErrorMessage("");

    try {
      await authService.login(formData);
      setSubmitStatus("success");
      setFormData({ username: "", password: "" });
      navigate("/");
    } catch (error) {
      setSubmitStatus("error");
      if (axios.isAxiosError(error)) {
        setErrorMessage(
          error.response?.data?.detail || error.message || "Invalid credentials"
        );
      } else if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("An error occurred during login");
      }
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
    <form className="login-form" onSubmit={handleSubmit}>
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
      <button type="submit" disabled={isSubmitting} className="login-button">
        {isSubmitting ? "Logging in..." : "Login"}
      </button>
      {submitStatus === "success" && (
        <p className="status-message success">Login successful!</p>
      )}
      {submitStatus === "error" && (
        <p className="status-message error">Error: {errorMessage}</p>
      )}
    </form>
  );
};

export default LoginForm;
