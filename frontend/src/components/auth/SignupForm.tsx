import React, { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { authService, SignupConfig } from "../../services/authService";
import { getUserFacingError } from "../../services/apiClient";
import "../../styles/auth-styles.css";

interface FormData {
  username: string;
  password: string;
  inviteCode: string;
}

const SignupForm: React.FC = () => {
  const [params] = useSearchParams();
  const [formData, setFormData] = useState<FormData>({
    username: "",
    password: "",
    inviteCode: params.get("invite") || "",
  });
  const [config, setConfig] = useState<SignupConfig | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const navigate = useNavigate();
  const { register } = useAuth();

  useEffect(() => {
    let cancelled = false;
    authService
      .signupConfig()
      .then((next) => { if (!cancelled) setConfig(next); })
      // Unknown policy: show the form and let the server decide.
      .catch(() => { if (!cancelled) setConfig({ signup_mode: "open", first_user: false }); });
    return () => { cancelled = true; };
  }, []);

  const needsInvite = config?.signup_mode === "invite" && !config.first_user;
  const closed = config?.signup_mode === "closed" && !config.first_user;

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");

    try {
      await register({
        username: formData.username,
        password: formData.password,
        invite_code: needsInvite ? formData.inviteCode.trim() : undefined,
      });
      navigate("/");
    } catch (error) {
      setErrorMessage(getUserFacingError(error, "Error signing up. Please try again."));
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

  if (!config) {
    return <p className="status-message" role="status">Loading…</p>;
  }

  if (closed) {
    return (
      <p className="status-message error" role="status">
        Sign-up is closed on this Nexus instance. Ask the administrator for an account or an invite.
      </p>
    );
  }

  return (
    <form className="signup-form" onSubmit={handleSubmit}>
      {config.first_user && (
        <p className="status-message success">This is the first account; it will administer this Nexus instance.</p>
      )}
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
          autoComplete="username"
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
          minLength={8}
          autoComplete="new-password"
          className="form-input"
        />
      </div>

      {needsInvite && (
        <div className="form-group">
          <label htmlFor="inviteCode" className="form-label">
            Invite code:
          </label>
          <input
            id="inviteCode"
            name="inviteCode"
            type="text"
            value={formData.inviteCode}
            onChange={handleChange}
            required
            autoComplete="off"
            className="form-input"
          />
        </div>
      )}

      <button type="submit" disabled={isSubmitting} className="submit-button">
        {isSubmitting ? "Submitting..." : "Submit"}
      </button>

      {errorMessage && <p className="status-message error">{errorMessage}</p>}
    </form>
  );
};

export default SignupForm;
