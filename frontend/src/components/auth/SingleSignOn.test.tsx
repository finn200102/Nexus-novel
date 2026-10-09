import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SingleSignOn from "./SingleSignOn";
import { authService } from "../../services/authService";

vi.mock("../../services/authService", () => ({
  authService: { signupConfig: vi.fn(), singleSignOnUrl: () => "/api/auth/oidc/login" },
}));

const config = vi.mocked(authService.signupConfig);

const renderAt = (url = "/login") =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <SingleSignOn>
        <form aria-label="password form" />
      </SingleSignOn>
    </MemoryRouter>,
  );

describe("SingleSignOn", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers the provider next to the password form", async () => {
    config.mockResolvedValue({ signup_mode: "closed", first_user: false, password_login: true, oidc: { display_name: "Authelia" } });
    renderAt();
    expect(await screen.findByRole("button", { name: "Sign in with Authelia" })).toBeTruthy();
    expect(screen.getByRole("form", { name: "password form" })).toBeTruthy();
  });

  it("hides the password form when password sign-in is disabled", async () => {
    config.mockResolvedValue({ signup_mode: "closed", first_user: false, password_login: false, oidc: { display_name: "Authentik" } });
    renderAt();
    await screen.findByRole("button", { name: "Sign in with Authentik" });
    expect(screen.queryByRole("form", { name: "password form" })).toBeNull();
  });

  it("shows only the password form without single sign-on", async () => {
    config.mockResolvedValue({ signup_mode: "open", first_user: false, password_login: true, oidc: null });
    renderAt();
    expect(await screen.findByRole("form", { name: "password form" })).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("explains a failed sign-in", async () => {
    config.mockResolvedValue({ signup_mode: "closed", first_user: false, oidc: { display_name: "Keycloak" } });
    renderAt("/login?sso_error=no_account");
    expect((await screen.findByRole("alert")).textContent).toContain("No Nexus account is linked");
  });
});
