import React, { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { useAuth } from "../../context/AuthContext";
import { Banner, Button, Input } from "../ui";

const LoginForm: React.FC = () => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { login, isAuthenticated } = useAuth();

  useEffect(() => {
    // A restored session (refresh cookie) needs no new sign-in.
    if (isAuthenticated) navigate("/", { replace: true });
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await login(username, password);
      navigate("/");
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
      setErrorMessage(
        typeof detail === "string" && detail
          ? detail
          : axios.isAxiosError(error) && !error.response
            ? "We couldn't reach the server. Check your connection and try again."
            : "That username and password don't match. Try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      {params.get("reset") && !errorMessage && (
        <Banner tone="success">Password changed. Sign in with your new password.</Banner>
      )}
      <Input label="Username" name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
      <Input
        label="Password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      {errorMessage && <p className="auth-form__error" role="alert">{errorMessage}</p>}
      <Button type="submit" variant="primary" size="lg" block loading={isSubmitting}>
        Sign in
      </Button>
    </form>
  );
};

export default LoginForm;
