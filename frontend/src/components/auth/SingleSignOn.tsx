import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { authService, SignupConfig } from "../../services/authService";
import { Banner, Button } from "../ui";
import { ssoErrorMessage } from "./ssoErrors";

interface SingleSignOnProps {
  /** The password form; hidden when the instance disables password sign-in. */
  children: React.ReactNode;
}

/** "Sign in with <provider>" above the password form, when configured. */
const SingleSignOn: React.FC<SingleSignOnProps> = ({ children }) => {
  const [config, setConfig] = useState<SignupConfig | null>(null);
  const [redirecting, setRedirecting] = useState(false);
  const [params] = useSearchParams();
  const error = params.get("sso_error");

  useEffect(() => {
    let active = true;
    authService
      .signupConfig()
      .then((value) => active && setConfig(value))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const provider = config?.oidc?.display_name;
  const passwordLogin = config?.password_login !== false;

  return (
    <>
      {error && <Banner tone="danger" urgent>{ssoErrorMessage(error)}</Banner>}
      {provider && (
        <div className="auth-sso">
          <Button
            variant={passwordLogin ? "secondary" : "primary"}
            size="lg"
            block
            icon={<KeyRound aria-hidden="true" />}
            loading={redirecting}
            onClick={() => {
              setRedirecting(true);
              window.location.assign(authService.singleSignOnUrl());
            }}
          >
            Sign in with {provider}
          </Button>
          {passwordLogin && <p className="auth-sso__divider">or use your password</p>}
        </div>
      )}
      {passwordLogin && children}
    </>
  );
};

export default SingleSignOn;
