import React, { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import AuthLayout from "../components/auth/AuthLayout";
import { authService } from "../services/authService";
import { getUserFacingError } from "../services/apiClient";
import { Banner, Button, Input } from "../components/ui";

const ResetPasswordPage: React.FC = () => {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    setIsSubmitting(true);
    setError("");
    try {
      await authService.resetPassword(token, password);
      navigate("/login?reset=1", { replace: true });
    } catch (err) {
      setError(getUserFacingError(err, "This password reset link is invalid or has expired."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Choose a new password"
      description="Use at least 8 characters."
      footer={<p>Remembered it? <Link to="/login">Sign in</Link></p>}
    >
      {!token ? (
        <Banner tone="warning">This link is missing its reset code. Ask the person who runs this server for a new link.</Banner>
      ) : (
        <form className="auth-form" onSubmit={handleSubmit}>
          <Input label="New password" type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <Input label="Repeat password" type="password" required minLength={8} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {error && <p className="auth-form__error" role="alert">{error}</p>}
          <Button type="submit" variant="primary" size="lg" block loading={isSubmitting}>
            Set password
          </Button>
        </form>
      )}
    </AuthLayout>
  );
};

export default ResetPasswordPage;
