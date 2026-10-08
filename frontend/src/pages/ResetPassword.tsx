import React, { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import AuthLayout from "../components/auth/AuthLayout";
import { authService } from "../services/authService";
import { getUserFacingError } from "../services/apiClient";
import "../styles/auth-styles.css";

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
      subtitle="Password reset"
      footer={<p>Remembered it? <Link to="/login">Sign in</Link></p>}
    >
      {!token ? (
        <p className="status-message error">This link is missing its reset code. Ask your administrator for a new link.</p>
      ) : (
        <form className="login-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="new-password" className="form-label">New password:</label>
            <input id="new-password" type="password" required minLength={8} autoComplete="new-password" className="form-input" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div className="form-group">
            <label htmlFor="confirm-password" className="form-label">Repeat password:</label>
            <input id="confirm-password" type="password" required minLength={8} autoComplete="new-password" className="form-input" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </div>
          <button type="submit" disabled={isSubmitting} className="login-button">
            {isSubmitting ? "Saving..." : "Set password"}
          </button>
          {error && <p className="status-message error">{error}</p>}
        </form>
      )}
    </AuthLayout>
  );
};

export default ResetPasswordPage;
