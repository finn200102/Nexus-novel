import React, { useState } from "react";
import { KeyRound, LogOut } from "lucide-react";
import { authService } from "../services/authService";
import { getUserFacingError } from "../services/apiClient";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/useToast";
import EReaderSettings from "../components/ereader/EReaderSettings";
import "../styles/operations.css";
import "../styles/integrations.css";
import "../styles/accounts.css";

const Account: React.FC = () => {
  const { user } = useAuth();
  const { addToast } = useToast();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [saving, setSaving] = useState(false);

  const changePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    if (form.next !== form.confirm) {
      addToast("The new passwords do not match", "error");
      return;
    }
    setSaving(true);
    try {
      await authService.changePassword(form.current, form.next);
      setForm({ current: "", next: "", confirm: "" });
      addToast("Password changed. Other devices were signed out.", "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not change the password"), "error");
    } finally {
      setSaving(false);
    }
  };

  const signOutOthers = async () => {
    try {
      const count = await authService.logoutOtherDevices();
      addToast(count === 1 ? "Signed out 1 other device" : `Signed out ${count} other devices`, "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not sign out other devices"), "error");
    }
  };

  return (
    <div className="integrations-page account-page">
      <header className="integrations-page__header">
        <div>
          <p className="library-workspace__eyebrow">Your account</p>
          <h1>{user?.username}</h1>
          <p>{user?.is_admin ? "Administrator" : "Reader"}</p>
        </div>
      </header>

      <article className="integrations-panel">
        <header>
          <div>
            <h2>Change password</h2>
            <p>At least 8 characters. Your other devices will be signed out.</p>
          </div>
        </header>
        <form className="account-form" onSubmit={changePassword}>
          <label>
            Current password
            <input type="password" required autoComplete="current-password" value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} />
          </label>
          <label>
            New password
            <input type="password" required minLength={8} autoComplete="new-password" value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} />
          </label>
          <label>
            Repeat new password
            <input type="password" required minLength={8} autoComplete="new-password" value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
          </label>
          <button className="operations-action" disabled={saving}><KeyRound size={14} /> Change password</button>
        </form>
      </article>

      <article className="integrations-panel">
        <header>
          <div>
            <h2>Signed-in devices</h2>
            <p>Lost a device or used a shared computer? End every session except this one.</p>
          </div>
        </header>
        <div className="account-form">
          <button type="button" className="operations-action operations-action--quiet" onClick={() => void signOutOthers()}>
            <LogOut size={14} /> Sign out other devices
          </button>
        </div>
      </article>

      <EReaderSettings />
    </div>
  );
};

export default Account;
