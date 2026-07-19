import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import SignupForm from "../../src/components/auth/SignupForm";
import apiClient from "../../src/services/apiClient";
import { AuthProvider } from "../../src/context/AuthContext";

vi.mock("../../src/services/apiClient");

const mockedApiClient = apiClient as jest.Mocked<typeof apiClient>;

const renderWithRouter = (ui: React.ReactElement) => {
  return render(
    <MemoryRouter>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>
  );
};

describe("SignupForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the form correctly", () => {
    renderWithRouter(<SignupForm />);

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
  });

  it("updates form values when user types", async () => {
    renderWithRouter(<SignupForm />);
    const user = userEvent.setup();

    const usernameInput = screen.getByLabelText(/username/i);
    const passwordInput = screen.getByLabelText(/password/i);

    await user.type(usernameInput, "testuser");
    await user.type(passwordInput, "password123");

    expect(usernameInput).toHaveValue("testuser");
    expect(passwordInput).toHaveValue("password123");
  });

  it("submits the form and shows success message", async () => {
    mockedApiClient.post.mockResolvedValueOnce({ data: { success: true } });

    renderWithRouter(<SignupForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/username/i), "testuser");
    await user.type(screen.getByLabelText(/password/i), "password123");

    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(mockedApiClient.post).toHaveBeenCalledWith("/auth/signup", {
      username: "testuser",
      password: "password123",
    });

    await waitFor(() => {
      expect(screen.getByText(/signup successful/i)).toBeInTheDocument();
    });

    expect(screen.getByLabelText(/username/i)).toHaveValue("");
    expect(screen.getByLabelText(/password/i)).toHaveValue("");
  });

  it("shows error message when API call fails", async () => {
    mockedApiClient.post.mockRejectedValueOnce(new Error("API Error"));

    renderWithRouter(<SignupForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/username/i), "testuser");
    await user.type(screen.getByLabelText(/password/i), "password123");

    await user.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() => {
      expect(screen.getByText(/error signing up/i)).toBeInTheDocument();
    });

    expect(screen.getByLabelText(/username/i)).toHaveValue("testuser");
    expect(screen.getByLabelText(/password/i)).toHaveValue("password123");
  });

  it("disables submit button while submitting", async () => {
    mockedApiClient.post.mockImplementationOnce(
      () =>
        new Promise((resolve) =>
          setTimeout(() => resolve({ data: { success: true } }), 100)
        )
    );

    renderWithRouter(<SignupForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/username/i), "testuser");
    await user.type(screen.getByLabelText(/password/i), "password123");
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByText(/submitting/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("button")).not.toBeDisabled();
      expect(
        screen.getByRole("button", { name: /submit/i })
      ).toBeInTheDocument();
    });
  });
});
