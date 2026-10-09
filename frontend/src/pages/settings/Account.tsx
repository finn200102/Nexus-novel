import React, { useState } from "react";
import { LogOut } from "lucide-react";
import { authService } from "../../services/authService";
import { getUserFacingError } from "../../services/apiClient";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/useToast";
import { usePageTitle } from "../../hooks/usePageTitle";
import { Button, Input, PageHeader } from "../../components/ui";
import { SETTINGS_BACK } from "./settingsNav";

const SettingsAccount: React.FC = () => {
  usePageTitle("Profile & security", { back: SETTINGS_BACK });
  const { user } = useAuth();
  const { addToast } = useToast();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [saving, setSaving] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

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
    setSigningOut(true);
    try {
      const count = await authService.logoutOtherDevices();
      addToast(count === 1 ? "Signed out 1 other device" : `Signed out ${count} other devices`, "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not sign out other devices"), "error");
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Profile & security"
        description={`Signed in as ${user?.username ?? "you"}${user?.is_admin ? " (administrator)" : ""}.`}
      />

      <section className="settings-group" aria-labelledby="settings-password">
        <h2 id="settings-password">Change password</h2>
        <p className="settings-group__hint">Use at least 8 characters. Your other devices will be signed out.</p>
        <form className="settings-form" onSubmit={changePassword}>
          <Input
            label="Current password"
            type="password"
            required
            autoComplete="current-password"
            value={form.current}
            onChange={(e) => setForm({ ...form, current: e.target.value })}
          />
          <Input
            label="New password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={form.next}
            onChange={(e) => setForm({ ...form, next: e.target.value })}
          />
          <Input
            label="Repeat new password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={form.confirm}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })}
          />
          <div>
            <Button type="submit" variant="primary" loading={saving}>
              Change password
            </Button>
          </div>
        </form>
      </section>

      <section className="settings-group" aria-labelledby="settings-devices">
        <h2 id="settings-devices">Signed-in devices</h2>
        <p className="settings-group__hint">
          Lost a device or used a shared computer? Sign out every other device. This one stays signed in.
        </p>
        <div>
          <Button variant="secondary" icon={<LogOut aria-hidden="true" />} loading={signingOut} onClick={() => void signOutOthers()}>
            Sign out other devices
          </Button>
        </div>
      </section>
    </>
  );
};

export default SettingsAccount;
