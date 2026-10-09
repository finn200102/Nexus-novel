import React, { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { authService, SignupConfig } from "../../services/authService";
import { getUserFacingError } from "../../services/apiClient";
import { Banner, Button, Input } from "../ui";

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
      setErrorMessage(getUserFacingError(error, "We couldn't create the account. Try again."));
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
    return <p className="text-secondary" role="status">Loading…</p>;
  }

  if (closed) {
    return (
      <Banner tone="info">
        New accounts are turned off on this server. Ask the person who runs it for an account or an invite.
      </Banner>
    );
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      {config.first_user && (
        <Banner tone="info">This is the first account, so it can manage this server (users, sites, backups).</Banner>
      )}
      <Input label="Username" id="username" name="username" value={formData.username} onChange={handleChange} required autoComplete="username" />
      <Input
        label="Password"
        id="password"
        name="password"
        type="password"
        hint="At least 8 characters."
        value={formData.password}
        onChange={handleChange}
        required
        minLength={8}
        autoComplete="new-password"
      />
      {needsInvite && (
        <Input
          label="Invite code"
          id="inviteCode"
          name="inviteCode"
          hint="From the invite link or message you got."
          value={formData.inviteCode}
          onChange={handleChange}
          required
          autoComplete="off"
        />
      )}
      {errorMessage && <p className="auth-form__error" role="alert">{errorMessage}</p>}
      <Button type="submit" variant="primary" size="lg" block loading={isSubmitting}>
        Create account
      </Button>
    </form>
  );
};

export default SignupForm;
