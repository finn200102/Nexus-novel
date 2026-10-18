import { act, render, screen, waitFor } from "@testing-library/react";
import { AxiosAdapter, AxiosError, InternalAxiosRequestConfig } from "axios";
import axios from "axios";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AuthProvider, useAuth } from "../../src/context/AuthContext";
import { readSignedInMarker, writeSignedInMarker } from "../../src/services/authService";

type Outcome = "ok" | "network" | "unauthorized";
let outcome: Outcome = "ok";

const session = {
  id: 7,
  username: "reader",
  message: "ok",
  access_token: "token",
  token_type: "bearer",
  expires_in: 900,
  is_admin: false,
};
let responseSession = session;

const refreshAdapter = ((config: InternalAxiosRequestConfig) => {
  if (outcome === "network") {
    return Promise.reject(new AxiosError("Network Error", "ERR_NETWORK", config, null));
  }
  if (outcome === "unauthorized") {
    const response = { data: { detail: "Session ended" }, status: 401, statusText: "401", headers: {}, config };
    return Promise.reject(new AxiosError("HTTP 401", "401", config, null, response));
  }
  return Promise.resolve({ data: responseSession, status: 200, statusText: "OK", headers: {}, config });
}) as AxiosAdapter;

const Probe = () => {
  const { isAuthenticated, isOffline, isLoading, offlineUser, user } = useAuth();
  return (
    <div>
      <span data-testid="state">{isLoading ? "loading" : isAuthenticated ? "in" : "out"}</span>
      <span data-testid="offline">{isOffline ? "offline" : "online"}</span>
      <span data-testid="who">{offlineUser?.username ?? "none"}</span>
      <span data-testid="account">{user?.id ?? offlineUser?.id ?? "none"}</span>
    </div>
  );
};

const renderProbe = () => render(<AuthProvider><Probe /></AuthProvider>);

describe("AuthContext offline state", () => {
  const originalAdapter = axios.defaults.adapter;

  beforeEach(() => {
    localStorage.clear();
    outcome = "ok";
    responseSession = session;
    axios.defaults.adapter = refreshAdapter;
  });

  afterEach(() => {
    axios.defaults.adapter = originalAdapter;
  });

  it("stays offline-signed-in when the refresh fails with a network error and a marker exists", async () => {
    writeSignedInMarker({ id: 7, username: "reader", is_admin: false });
    outcome = "network";
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("in"));
    expect(screen.getByTestId("offline").textContent).toBe("offline");
    expect(screen.getByTestId("who").textContent).toBe("reader");
    expect(readSignedInMarker()).toEqual({ id: 7, username: "reader", is_admin: false });
  });

  it("signs out when the refresh is rejected with 401, even with a marker", async () => {
    writeSignedInMarker({ id: 7, username: "reader", is_admin: false });
    outcome = "unauthorized";
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("out"));
    expect(screen.getByTestId("offline").textContent).toBe("online");
    expect(readSignedInMarker()).toBeNull();
  });

  it("does not enter offline mode on a network error without a marker", async () => {
    outcome = "network";
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("out"));
    expect(screen.getByTestId("offline").textContent).toBe("online");
  });

  it("leaves offline mode when the browser comes back online and the refresh succeeds", async () => {
    writeSignedInMarker({ id: 7, username: "reader", is_admin: false });
    outcome = "network";
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("offline").textContent).toBe("offline"));
    outcome = "ok";
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(screen.getByTestId("offline").textContent).toBe("online"));
    expect(screen.getByTestId("state").textContent).toBe("in");
  });

  it("removes the active session when another tab signs out", async () => {
    writeSignedInMarker({ id: 7, username: "reader", is_admin: false });
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("in"));
    await act(async () => {
      localStorage.removeItem("nexus-signed-in");
      window.dispatchEvent(new StorageEvent("storage", { key: "nexus-signed-in", newValue: null }));
    });
    expect(screen.getByTestId("state").textContent).toBe("out");
  });

  it("preserves a newer account marker when a delayed logout event arrives", async () => {
    writeSignedInMarker({ id: 7, username: "reader", is_admin: false });
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("account").textContent).toBe("7"));
    responseSession = { ...session, id: 8, username: "next-reader" };
    await act(async () => {
      writeSignedInMarker(responseSession);
      window.dispatchEvent(new StorageEvent("storage", { key: "nexus-signed-in", newValue: null }));
    });
    await waitFor(() => expect(screen.getByTestId("account").textContent).toBe("8"));
    expect(readSignedInMarker()?.id).toBe(8);
  });
});
