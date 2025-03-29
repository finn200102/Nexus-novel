import React, { FormEvent, useEffect } from "react";
import { useState } from "react";
import axios from "axios";
import "../../styles/auth-styles.css";

interface FormData {
  username: string;
  password: string;
}

interface LoginResponse {
  id: number;
  username: string;
  message: string;
  access_token: string;
  token_type: string;
}

const LoginForm: React.FC = () => {
  const [formData, setFormData] = useState<FormData>({
    username: "",
    password: "",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<"success" | "error" | null>(
    null
  );
  const [errorMessage, setErrorMessage] = useState<string>("");

  // Check for token on component mount
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      // Set global axios auth header
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
      console.log("Set global Authorization header with token");
    }
    console.log(
      "Initial token check:",
      token ? `${token.substring(0, 15)}...` : "null"
    );
  }, []);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitStatus(null);
    setErrorMessage("");

    try {
      console.log("Submitting login with:", formData.username);

      // Send JSON data
      const response = await axios.post<LoginResponse>("/api/auth/login", {
        username: formData.username,
        password: formData.password,
      });

      console.log("Login response:", response.data);

      // Check if we have the expected structure
      if (!response.data) {
        throw new Error("Empty response from server");
      }

      const { access_token, token_type } = response.data;

      if (!access_token) {
        console.error("No access_token in response data:", response.data);
        throw new Error(
          `No access_token in response. Response keys: ${Object.keys(
            response.data
          ).join(", ")}`
        );
      }

      // Save JWT token to localStorage
      localStorage.setItem("token", access_token);

      // Set Authorization header for future requests
      // OAuth2PasswordBearer expects "Bearer {token}" format
      axios.defaults.headers.common["Authorization"] = `Bearer ${access_token}`;
      console.log(
        "Set global Authorization header:",
        `Bearer ${access_token.substring(0, 15)}...`
      );

      console.log(
        "Login successful, token stored:",
        access_token.substring(0, 20) + "..."
      );

      setSubmitStatus("success");
      setFormData({ username: "", password: "" });

      // Test the token immediately with a simple request
      try {
        const testResponse = await axios.get("/api/library", {
          headers: {
            Authorization: `Bearer ${access_token}`,
          },
        });
        console.log("Test request successful:", testResponse.data);
      } catch (testError) {
        console.error("Test request failed:", testError);
      }
    } catch (error) {
      setSubmitStatus("error");
      if (axios.isAxiosError(error)) {
        console.error("Login error response:", error.response?.data);
        console.error("Status:", error.response?.status);

        setErrorMessage(
          error.response?.data?.detail || error.message || "Invalid credentials"
        );
      } else if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("An error occurred during login");
      }
      console.error("Error logging in:", error);
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
    <div className="login-container">
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
    </div>
  );
};

export default LoginForm;
