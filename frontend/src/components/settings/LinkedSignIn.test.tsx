import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LinkedSignIn from "./LinkedSignIn";
import { authService, LinkedSignInStatus } from "../../services/authService";

const addToast = vi.fn();
vi.mock("../../context/useToast", () => ({ useToast: () => ({ addToast }) }));
vi.mock("../../services/authService", () => ({
  authService: { startLinkingSignIn: vi.fn(), unlinkSignIn: vi.fn() },
}));

const service = vi.mocked(authService);
const base: LinkedSignInStatus = { enabled: true, display_name: "Authelia", linked: false, has_password: true, password_login: true };

const renderWith = (status: LinkedSignInStatus | null, onChange = vi.fn()) =>
  render(
    <MemoryRouter>
      <LinkedSignIn status={status} onChange={onChange} />
    </MemoryRouter>,
  );

describe("LinkedSignIn", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders nothing when single sign-on is off", () => {
    const { container } = renderWith({ ...base, enabled: false });
    expect(container.textContent).toBe("");
  });

  it("starts linking at the provider", async () => {
    service.startLinkingSignIn.mockResolvedValue("https://idp.example/authorize?x=1");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    renderWith(base);
    fireEvent.click(screen.getByRole("button", { name: "Link Authelia" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://idp.example/authorize?x=1"));
    vi.unstubAllGlobals();
  });

  it("unlinks when a password remains", async () => {
    service.unlinkSignIn.mockResolvedValue();
    const onChange = vi.fn();
    renderWith({ ...base, linked: true }, onChange);
    fireEvent.click(screen.getByRole("button", { name: "Unlink Authelia" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
  });

  it("can't unlink the only sign-in method", () => {
    renderWith({ ...base, linked: true, has_password: false });
    expect((screen.getByRole("button", { name: "Unlink Authelia" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/only way to sign in/)).toBeTruthy();
  });
});
