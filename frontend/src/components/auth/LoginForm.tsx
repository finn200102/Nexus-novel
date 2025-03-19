import React, { FormEvent, useEffect } from "react";
import { useState } from "react";
import axios from "axios";

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
  const [storedToken, setStoredToken] = useState<string | null>(null);
  const [responseDebug, setResponseDebug] = useState<string>("");

  // Check for token on component mount
  useEffect(() => {
    const token = localStorage.getItem("token");
    setStoredToken(token);
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
    setResponseDebug("");

    try {
      console.log("Submitting login with:", formData.username);

      // Send JSON data
      const response = await axios.post<LoginResponse>("/api/auth/login", {
        username: formData.username,
        password: formData.password,
      });

      console.log("Login response:", response.data);
      setResponseDebug(JSON.stringify(response.data, null, 2));

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
      setStoredToken(access_token);

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

        if (error.response?.data) {
          setResponseDebug(JSON.stringify(error.response.data, null, 2));
        }

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
  // Add this to your LoginForm component
  const testToken = async () => {
    const token = localStorage.getItem("token");
    if (!token) {
      console.error("No token found");
      return;
    }

    try {
      console.log("Testing token:", token.substring(0, 20) + "...");
      const response = await axios.get("/api/auth/verify-token", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      console.log("Token verification successful:", response.data);
      alert("Token is valid! User: " + response.data.username);
    } catch (error) {
      console.error("Token verification failed:", error);
      if (axios.isAxiosError(error)) {
        console.error("Response data:", error.response?.data);
        console.error("Status:", error.response?.status);
      }
      alert("Token verification failed!");
    }
  };

  // Add a button to your debug section

  return (
    <div>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="username">Username:</label>
          <input
            id="username"
            name="username"
            type="text"
            value={formData.username}
            onChange={handleChange}
            required
          />
        </div>
        <div>
          <label htmlFor="password">Password:</label>
          <input
            id="password"
            name="password"
            type="password"
            value={formData.password}
            onChange={handleChange}
            required
          />
        </div>
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Logging in..." : "Login"}
        </button>
        {submitStatus === "success" && <p>Login successful!</p>}
        {submitStatus === "error" && <p>Error: {errorMessage}</p>}
      </form>

      {/* Debug section */}
      <div
        style={{
          marginTop: "20px",
          padding: "10px",
          border: "1px solid #ccc",
          borderRadius: "5px",
        }}
      >
        <h4>Debug Info</h4>
        <button onClick={testToken}>Test Token</button>
        <p>
          Stored Token:{" "}
          {storedToken ? `${storedToken.substring(0, 15)}...` : "None"}
        </p>
        <button
          onClick={() => {
            const token = localStorage.getItem("token");
            setStoredToken(token);
            console.log("Current token:", token);

            // Test the token with a request
            if (token) {
              axios
                .get("/api/library", {
                  headers: {
                    Authorization: `Bearer ${token}`,
                  },
                })
                .then((response) =>
                  console.log("Test request successful:", response.data)
                )
                .catch((error) => console.error("Test request failed:", error));
            }
          }}
        >
          Check Token & Test
        </button>

        {responseDebug && (
          <div>
            <h5>Response Data:</h5>
            <pre
              style={{
                background: "#f5f5f5",
                padding: "10px",
                overflow: "auto",
                maxHeight: "200px",
                fontSize: "12px",
              }}
            >
              {responseDebug}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
};

export default LoginForm;
