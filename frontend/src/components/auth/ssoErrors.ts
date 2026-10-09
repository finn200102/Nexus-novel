/** Messages for the `sso_error` codes the single sign-on callback returns. */
export const SSO_ERRORS: Record<string, string> = {
  state: "That sign-in link expired or was already used. Try again.",
  denied: "The sign-in was cancelled.",
  invalid_token: "The sign-in provider's answer could not be verified. Try again or ask your administrator.",
  exchange_failed: "The sign-in provider did not accept the sign-in. Try again.",
  provider_unavailable: "The sign-in provider can't be reached right now. Try again later.",
  provider_misconfigured: "Single sign-on is not set up correctly. Ask your administrator.",
  no_account:
    "No Nexus account is linked to this sign-in. Sign in with your password and link it under Settings → Profile & security, or ask your administrator.",
  disabled: "This account is disabled. Ask your administrator.",
  already_linked: "That sign-in is already linked to a different Nexus account.",
};

export const ssoErrorMessage = (code: string) => SSO_ERRORS[code] ?? "Single sign-on failed. Try again.";
