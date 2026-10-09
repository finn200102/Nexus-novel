import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { authService, LinkedSignInStatus } from "../../services/authService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { Banner, Button } from "../ui";
import { ssoErrorMessage } from "../auth/ssoErrors";

interface LinkedSignInProps {
  status: LinkedSignInStatus | null;
  onChange: () => void;
}

/** Settings → Profile & security: link or unlink the single sign-on identity. */
const LinkedSignIn: React.FC<LinkedSignInProps> = ({ status, onChange }) => {
  const { addToast } = useToast();
  const [params] = useSearchParams();
  const [busy, setBusy] = useState(false);
  if (!status?.enabled) return null;

  const provider = status.display_name;
  const onlyMethod = !status.has_password || !status.password_login;
  const error = params.get("sso_error");

  const link = async () => {
    setBusy(true);
    try {
      window.location.assign(await authService.startLinkingSignIn());
    } catch (err) {
      addToast(getUserFacingError(err, `Could not reach ${provider}`), "error");
      setBusy(false);
    }
  };

  const unlink = async () => {
    setBusy(true);
    try {
      await authService.unlinkSignIn();
      addToast(`${provider} sign-in unlinked`, "success");
      onChange();
    } catch (err) {
      addToast(getUserFacingError(err, "Could not unlink the sign-in"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="settings-group" aria-labelledby="settings-linked-sign-in">
      <h2 id="settings-linked-sign-in">Linked sign-in</h2>
      {error && <Banner tone="danger">{ssoErrorMessage(error)}</Banner>}
      {params.get("sso") === "linked" && !error && status.linked && (
        <Banner tone="success">You can now sign in with {provider}.</Banner>
      )}
      {status.linked ? (
        <>
          <p className="settings-group__hint">
            This account is linked to {provider}.
            {onlyMethod && " It is your only way to sign in, so it can't be unlinked."}
          </p>
          <div>
            <Button variant="secondary" loading={busy} disabled={onlyMethod} onClick={() => void unlink()}>
              Unlink {provider}
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="settings-group__hint">
            Link {provider} to sign in to this account with it. You'll be sent to {provider} to confirm.
          </p>
          <div>
            <Button variant="secondary" icon={<KeyRound aria-hidden="true" />} loading={busy} onClick={() => void link()}>
              Link {provider}
            </Button>
          </div>
        </>
      )}
    </section>
  );
};

export default LinkedSignIn;
