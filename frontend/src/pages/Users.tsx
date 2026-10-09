import React, { useCallback, useEffect, useState } from "react";
import { Copy, Gauge, KeyRound, RefreshCw, ShieldCheck, ShieldOff, Ticket, Trash2, UserCheck, UserX } from "lucide-react";
import { Dialog, Button } from "../components/ui";
import { adminUserService, AdminUser, Invite } from "../services/adminUserService";
import type { SignupMode } from "../services/authService";
import { getUserFacingError } from "../services/apiClient";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/useToast";
import { ContentLimitsDialog } from "../components/household/ContentLimitsDialog";
import { describeLimits } from "../types/household";
import "../styles/operations.css";
import "../styles/integrations.css";
import "../styles/accounts.css";

const SIGNUP_MODES: { value: SignupMode; label: string; help: string }[] = [
  { value: "closed", label: "Closed", help: "Nobody can create an account." },
  { value: "invite", label: "Invite only", help: "New accounts need an invite code from you." },
  { value: "open", label: "Open", help: "Anyone who can reach this site can sign up." },
];

const formatDate = (value: string | null) => (value ? new Date(value).toLocaleString() : "never");

const copy = async (text: string, addToast: (message: string, type: "success" | "error") => void) => {
  try {
    await navigator.clipboard.writeText(text);
    addToast("Copied", "success");
  } catch {
    addToast("Copy failed; select the text instead", "error");
  }
};

const Users: React.FC = () => {
  const { user: me } = useAuth();
  const { addToast } = useToast();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [signupMode, setSignupMode] = useState<SignupMode>("closed");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newInvite, setNewInvite] = useState<Invite | null>(null);
  const [inviteForm, setInviteForm] = useState({ label: "", max_uses: "1", expires_in_days: "7" });
  const [resetLink, setResetLink] = useState<{ username: string; url: string; expires_at: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextUsers, nextInvites, settings] = await Promise.all([
        adminUserService.users(),
        adminUserService.invites(),
        adminUserService.settings(),
      ]);
      setUsers(nextUsers);
      setInvites(nextInvites);
      setSignupMode(settings.signup_mode);
    } catch (err) {
      setError(getUserFacingError(err, "User management is unavailable."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<unknown>, success: string, failure: string) => {
    try {
      await action();
      addToast(success, "success");
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, failure), "error");
    }
  };

  const changeSignupMode = async (mode: SignupMode) => {
    const previous = signupMode;
    setSignupMode(mode);
    try {
      await adminUserService.updateSettings(mode);
      addToast("Sign-up setting saved", "success");
    } catch (err) {
      setSignupMode(previous);
      addToast(getUserFacingError(err, "Could not change the sign-up setting"), "error");
    }
  };

  const createInvite = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const invite = await adminUserService.createInvite({
        label: inviteForm.label.trim() || undefined,
        max_uses: inviteForm.max_uses ? Number(inviteForm.max_uses) : null,
        expires_in_days: inviteForm.expires_in_days ? Number(inviteForm.expires_in_days) : null,
      });
      setNewInvite(invite);
      setInviteForm({ label: "", max_uses: "1", expires_in_days: "7" });
      await load();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not create the invite"), "error");
    }
  };

  const issueResetLink = async (user: AdminUser) => {
    try {
      const link = await adminUserService.passwordResetLink(user.id);
      setResetLink({ username: user.username, url: `${window.location.origin}${link.path}`, expires_at: link.expires_at });
    } catch (err) {
      addToast(getUserFacingError(err, "Could not create a reset link"), "error");
    }
  };

  const [pendingDelete, setPendingDelete] = useState<AdminUser | null>(null);
  const [limitsFor, setLimitsFor] = useState<AdminUser | null>(null);
  const deleteUser = (user: AdminUser) => {
    setPendingDelete(null);
    void run(() => adminUserService.deleteUser(user.id), `${user.username} deleted`, "Could not delete the user");
  };

  return (
    <div className="integrations-page">
      <header className="integrations-page__header">
        <div>
          <h2>Users &amp; invites</h2>
          <p>Decide who can sign up, hand out invites, and manage accounts.</p>
        </div>
        <button className="operations-refresh" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={16} className={loading ? "is-spinning" : ""} /> Refresh
        </button>
      </header>
      {error && <div className="integrations-alert"><ShieldCheck size={18} /> {error}</div>}

      <section className="integrations-grid">
        <article className="integrations-panel">
          <header>
            <div>
              <h2>Sign-up</h2>
              <p>Who may create a new account on this instance.</p>
            </div>
          </header>
          <div className="accounts-modes" role="radiogroup" aria-label="Sign-up mode">
            {SIGNUP_MODES.map((mode) => (
              <label key={mode.value} className={signupMode === mode.value ? "accounts-mode is-selected" : "accounts-mode"}>
                <input
                  type="radio"
                  name="signup-mode"
                  value={mode.value}
                  checked={signupMode === mode.value}
                  onChange={() => void changeSignupMode(mode.value)}
                />
                <span><strong>{mode.label}</strong><small>{mode.help}</small></span>
              </label>
            ))}
          </div>

          <h3 className="accounts-subheading">Invites</h3>
          <form className="integration-form accounts-invite-form" onSubmit={createInvite}>
            <input
              value={inviteForm.label}
              onChange={(e) => setInviteForm({ ...inviteForm, label: e.target.value })}
              placeholder="Who is it for? (optional)"
              aria-label="Invite label"
              maxLength={120}
            />
            <label>
              Uses
              <input
                type="number"
                min={1}
                max={1000}
                value={inviteForm.max_uses}
                onChange={(e) => setInviteForm({ ...inviteForm, max_uses: e.target.value })}
                placeholder="unlimited"
                aria-label="Invite uses"
              />
            </label>
            <label>
              Valid for days
              <input
                type="number"
                min={1}
                max={365}
                value={inviteForm.expires_in_days}
                onChange={(e) => setInviteForm({ ...inviteForm, expires_in_days: e.target.value })}
                placeholder="no expiry"
                aria-label="Invite validity in days"
              />
            </label>
            <button className="operations-action"><Ticket size={14} /> Create invite</button>
          </form>
          {signupMode !== "invite" && (
            <small className="integrations-event-help">Invite codes only work while sign-up is set to “Invite only”.</small>
          )}
          {newInvite?.code && (
            <div className="accounts-secret" role="status">
              <span>New invite code (shown once):</span>
              <code>{newInvite.code}</code>
              <button type="button" className="operations-action operations-action--quiet" onClick={() => void copy(newInvite.code!, addToast)}>
                <Copy size={14} /> Copy
              </button>
            </div>
          )}
          <div className="integrations-list">
            {invites.length === 0 && !loading && <p className="integrations-muted">No invites yet.</p>}
            {invites.map((invite) => (
              <div className="integration-row" key={invite.id}>
                <div>
                  <strong>
                    {invite.label || `Invite #${invite.id}`}{" "}
                    <span className={invite.status === "active" ? "integration-good" : "integration-warning"}>{invite.status}</span>
                  </strong>
                  <small>
                    {invite.use_count} / {invite.max_uses ?? "∞"} uses · expires {formatDate(invite.expires_at)}
                  </small>
                </div>
                <div className="integration-actions">
                  {invite.status === "active" && (
                    <button
                      className="operations-action operations-action--quiet"
                      onClick={() => void run(() => adminUserService.revokeInvite(invite.id), "Invite revoked", "Could not revoke the invite")}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="integrations-panel">
          <header>
            <div>
              <h2>Accounts</h2>
              <p>Disabling or resetting signs the user out everywhere. Nexus always keeps one active administrator.</p>
            </div>
            <span>{users.length} users</span>
          </header>
          {resetLink && (
            <div className="accounts-secret" role="status">
              <span>One-time reset link for {resetLink.username} (valid until {formatDate(resetLink.expires_at)}):</span>
              <code>{resetLink.url}</code>
              <button type="button" className="operations-action operations-action--quiet" onClick={() => void copy(resetLink.url, addToast)}>
                <Copy size={14} /> Copy
              </button>
            </div>
          )}
          <div className="integrations-list" aria-label="Users">
            {users.map((user) => {
              const isMe = user.id === me?.id;
              return (
                <div className="integration-row" key={user.id} data-testid={`user-row-${user.username}`}>
                  <div>
                    <strong>
                      {user.username}
                      {isMe && " (you)"}
                      {user.is_admin && <span className="integration-good">admin</span>}
                      {user.is_disabled && <span className="integration-warning"> disabled</span>}
                      {user.content_limits?.limited && <span className="integration-warning"> limited</span>}
                    </strong>
                    <small>
                      Last active {formatDate(user.last_seen_at)} · {user.active_sessions} signed-in device{user.active_sessions === 1 ? "" : "s"}
                      {user.content_limits?.limited && <> · {describeLimits(user.content_limits)}</>}
                    </small>
                  </div>
                  <div className="integration-actions">
                    <button
                      className="operations-action operations-action--quiet"
                      onClick={() =>
                        void run(
                          () => adminUserService.updateUser(user.id, { is_admin: !user.is_admin }),
                          user.is_admin ? `${user.username} is no longer an administrator` : `${user.username} is now an administrator`,
                          "Could not change administrator rights",
                        )
                      }
                    >
                      {user.is_admin ? <><ShieldOff size={14} /> Remove admin</> : <><ShieldCheck size={14} /> Make admin</>}
                    </button>
                    {!isMe && (
                      <button
                        className="operations-action operations-action--quiet"
                        onClick={() =>
                          void run(
                            () => adminUserService.updateUser(user.id, { is_disabled: !user.is_disabled }),
                            user.is_disabled ? `${user.username} enabled` : `${user.username} disabled`,
                            "Could not change the account",
                          )
                        }
                      >
                        {user.is_disabled ? <><UserCheck size={14} /> Enable</> : <><UserX size={14} /> Disable</>}
                      </button>
                    )}
                    <button
                      className="operations-action operations-action--quiet"
                      aria-label={`Content limits for ${user.username}`}
                      onClick={() => setLimitsFor(user)}
                    >
                      <Gauge size={14} /> Content limits
                    </button>
                    <button className="operations-action operations-action--quiet" onClick={() => void issueResetLink(user)}>
                      <KeyRound size={14} /> Reset link
                    </button>
                    {!isMe && (
                      <button className="operations-action operations-action--danger" onClick={() => setPendingDelete(user)}>
                        <Trash2 size={14} /> Delete
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </article>
      </section>
      <Dialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title={`Delete ${pendingDelete?.username ?? "this account"}?`}
        description="This also deletes their libraries, reading progress and history. This can't be undone."
        actions={<>
          <Button variant="ghost" onClick={() => setPendingDelete(null)}>Keep account</Button>
          <Button variant="danger" onClick={() => pendingDelete && deleteUser(pendingDelete)}>Delete account</Button>
        </>}
      />
      <ContentLimitsDialog
        user={limitsFor}
        onClose={() => setLimitsFor(null)}
        onSaved={(userId, limits) => setUsers((rows) => rows.map((row) => (row.id === userId ? { ...row, content_limits: limits } : row)))}
      />
    </div>
  );
};

export default Users;
