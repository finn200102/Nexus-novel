import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axios from "axios";
import SignupForm from "../../src/components/auth/SignupForm";

// Mock axios
vi.mock("axios");
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe("SignupForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the form correctly", () => {
    render(<SignupForm />);

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
  });

  it("updates form values when user types", async () => {
    render(<SignupForm />);
    const user = userEvent.setup();

    const usernameInput = screen.getByLabelText(/username/i);
    const passwordInput = screen.getByLabelText(/password/i);

    await user.type(usernameInput, "testuser");
    await user.type(passwordInput, "password123");

    expect(usernameInput).toHaveValue("testuser");
    expect(passwordInput).toHaveValue("password123");
  });

  it("submits the form and shows success message", async () => {
    // Mock successful API response
    mockedAxios.post.mockResolvedValueOnce({ data: { success: true } });

    render(<SignupForm />);
    const user = userEvent.setup();

    // Fill out the form
    await user.type(screen.getByLabelText(/username/i), "testuser");
    await user.type(screen.getByLabelText(/password/i), "password123");

    // Submit the form
    await user.click(screen.getByRole("button", { name: /submit/i }));

    // Check if axios was called with correct data
    expect(mockedAxios.post).toHaveBeenCalledWith("/api/signup", {
      username: "testuser",
      password: "password123",
    });

    // Check for success message
    await waitFor(() => {
      expect(screen.getByText(/signup successful/i)).toBeInTheDocument();
    });

    // Form should be reset
    expect(screen.getByLabelText(/username/i)).toHaveValue("");
    expect(screen.getByLabelText(/password/i)).toHaveValue("");
  });

  it("shows error message when API call fails", async () => {
    // Mock failed API response
    mockedAxios.post.mockRejectedValueOnce(new Error("API Error"));

    render(<SignupForm />);
    const user = userEvent.setup();

    // Fill out the form
    await user.type(screen.getByLabelText(/username/i), "testuser");
    await user.type(screen.getByLabelText(/password/i), "password123");

    // Submit the form
    await user.click(screen.getByRole("button", { name: /submit/i }));

    // Check for error message
    await waitFor(() => {
      expect(screen.getByText(/error signing up/i)).toBeInTheDocument();
    });

    // Form values should remain
    expect(screen.getByLabelText(/username/i)).toHaveValue("testuser");
    expect(screen.getByLabelText(/password/i)).toHaveValue("password123");
  });

  it("disables submit button while submitting", async () => {
    // Mock API with delay to test loading state
    mockedAxios.post.mockImplementationOnce(
      () =>
        new Promise((resolve) =>
          setTimeout(() => resolve({ data: { success: true } }), 100)
        )
    );

    render(<SignupForm />);
    const user = userEvent.setup();

    // Fill out and submit form
    await user.type(screen.getByLabelText(/username/i), "testuser");
    await user.type(screen.getByLabelText(/password/i), "password123");
    await user.click(screen.getByRole("button", { name: /submit/i }));

    // Button should be disabled during submission
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByText(/submitting/i)).toBeInTheDocument();

    // After submission completes
    await waitFor(() => {
      expect(screen.getByRole("button")).not.toBeDisabled();
      expect(
        screen.getByRole("button", { name: /submit/i })
      ).toBeInTheDocument();
    });
  });
});
