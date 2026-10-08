import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import SignupForm from "../../src/components/auth/SignupForm";
import { authService } from "../../src/services/authService";
import { AuthProvider } from "../../src/context/AuthContext";

vi.mock("../../src/services/authService", () => ({
  authService: {
    signupConfig: vi.fn(),
    register: vi.fn(),
    restore: vi.fn(),
  },
}));

const mocked = vi.mocked(authService);

const renderForm = (path = "/signup") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <SignupForm />
      </AuthProvider>
    </MemoryRouter>
  );

const fillCredentials = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(await screen.findByLabelText(/username/i), "testuser");
  await user.type(screen.getByLabelText(/^password/i), "password123");
};

describe("SignupForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.restore.mockResolvedValue(null);
    mocked.signupConfig.mockResolvedValue({ signup_mode: "open", first_user: false });
  });

  it("submits username and password when sign-up is open", async () => {
    mocked.register.mockResolvedValueOnce({} as never);
    renderForm();
    const user = userEvent.setup();

    await fillCredentials(user);
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(mocked.register).toHaveBeenCalledWith({ username: "testuser", password: "password123", invite_code: undefined });
    expect(screen.queryByLabelText(/invite code/i)).not.toBeInTheDocument();
  });

  it("tells the first user they will administer the instance", async () => {
    mocked.signupConfig.mockResolvedValueOnce({ signup_mode: "closed", first_user: true });
    renderForm();

    expect(await screen.findByText(/first account/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
  });

  it("asks for an invite code in invite mode and prefills it from the link", async () => {
    mocked.signupConfig.mockResolvedValueOnce({ signup_mode: "invite", first_user: false });
    mocked.register.mockResolvedValueOnce({} as never);
    renderForm("/signup?invite=abc123");
    const user = userEvent.setup();

    expect(await screen.findByLabelText(/invite code/i)).toHaveValue("abc123");
    await fillCredentials(user);
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(mocked.register).toHaveBeenCalledWith({ username: "testuser", password: "password123", invite_code: "abc123" });
  });

  it("explains that sign-up is closed", async () => {
    mocked.signupConfig.mockResolvedValueOnce({ signup_mode: "closed", first_user: false });
    renderForm();

    expect(await screen.findByText(/sign-up is closed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();
  });

  it("shows the server's error and keeps the input", async () => {
    mocked.register.mockRejectedValueOnce(new Error("API Error"));
    renderForm();
    const user = userEvent.setup();

    await fillCredentials(user);
    await user.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() => {
      expect(screen.getByText(/error signing up/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/username/i)).toHaveValue("testuser");
  });

  it("disables submit while submitting", async () => {
    let finish: () => void = () => undefined;
    mocked.register.mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve({} as never); }));
    renderForm();
    const user = userEvent.setup();

    await fillCredentials(user);
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(screen.getByRole("button", { name: /submitting/i })).toBeDisabled();
    finish();
  });
});
