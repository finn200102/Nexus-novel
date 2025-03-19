import React, { FormEvent } from "react";
import { useState } from "react";
import axios from "axios";

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
  const [submitStatus, setSubmitStatus] = useState<"success" | "error" | null>(
    null
  );
  const [errorMessage, setErrorMessage] = useState<string>("");

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitStatus(null);
    setErrorMessage("");

    try {
      const response = await axios.post("/auth/login", formData);
      const { token } = response.data;

      // Save JWT token to localStorage
      localStorage.setItem("jwt", token);

      // Set Authorization header for future requests
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;

      setSubmitStatus("success");
      setFormData({ username: "", password: "" });
    } catch (error) {
      setSubmitStatus("error");
      if (axios.isAxiosError(error) && error.response) {
        setErrorMessage(error.response.data.message || "Invalid credentials");
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
    <form onSubmit={handleSubmit}>
      <label htmlFor="username">Username:</label>
      <input
        id="username"
        name="username"
        type="text"
        value={formData.username}
        onChange={handleChange}
        required
      />
      <label htmlFor="password">Password:</label>
      <input
        id="password"
        name="password"
        type="password"
        value={formData.password}
        onChange={handleChange}
        required
      />
      <button type="submit" disabled={isSubmitting}>
        {isSubmitting ? "Logging in..." : "Login"}
      </button>
      {submitStatus === "success" && <p>Login successful!</p>}
      {submitStatus === "error" && <p>Error: {errorMessage}</p>}
    </form>
  );
};

export default LoginForm;
