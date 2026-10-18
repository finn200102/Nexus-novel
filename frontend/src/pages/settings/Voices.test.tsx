import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Voices from "./Voices";
import { accountStorage, activateAccountStorage } from "../../services/accountStorage";
import { voiceService, type NarratorVoice } from "../../services/voiceService";

vi.mock("../../services/pronunciationService",async original=>({...await original<typeof import("../../services/pronunciationService")>(),pronunciationService:{get:vi.fn(async()=>({scope:"pronunciation",revision:0,rules:[],account_rules:[],inherit_account:true,effective_rules:[],effective_version:null})),save:vi.fn()}}));
vi.mock("../../services/voiceService", () => ({ voiceService: { list: vi.fn(), capabilities: vi.fn(), remove: vi.fn(), getDefault:vi.fn(), setDefault:vi.fn() } }));
const voice: NarratorVoice = { id: 9, name: "My narrator", language: "English", status: "completed", transcript: "A reference", error: null, preview_ready: false };

describe("narrator voice settings", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(7);
    vi.mocked(voiceService.list).mockResolvedValue([voice]);
    vi.mocked(voiceService.capabilities).mockResolvedValue({ configured: true, languages: ["English"] });
    vi.mocked(voiceService.remove).mockResolvedValue(undefined);
    vi.mocked(voiceService.getDefault).mockImplementation(async()=>({ voice_profile_id:Number(accountStorage.getItem("nexus-reader-narrator-id")) || null, revision:2 }));
    vi.mocked(voiceService.setDefault).mockImplementation(async(id)=>({ voice_profile_id:id, revision:3 }));
  });
  afterEach(() => vi.restoreAllMocks());
  it("selects a saved private narrator for audio across stories", async () => {
    render(<Voices />);
    expect(screen.getByRole("heading", { name: /^Narrator voices$/ })).toBeInTheDocument();
    expect(screen.getByText(/any story/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/^Voice recording/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Use as narrator" }));
    await waitFor(()=>expect(accountStorage.getItem("nexus-reader-narrator-id")).toBe("9"));
    expect(voiceService.setDefault).toHaveBeenCalledWith(9,2);
    expect(accountStorage.getItem("nexus-reader-tts-engine")).toBe("openai_compatible");
    expect(accountStorage.getItem("nexus-reader-tts-preset")).toBe("qwen3_clone");
    expect(accountStorage.getItem("nexus-reader-tts-execution")).toBe("server");
    expect(screen.getByRole("button", { name: "Selected narrator" })).toBeInTheDocument();
  });
  it("restores the selection and clears it when its voice is deleted", async () => {
    accountStorage.setItem("nexus-reader-narrator-id", "9");
    accountStorage.setItem("nexus-reader-tts-preset", "qwen3_clone");
    accountStorage.setItem("nexus-reader-tts-engine", "openai_compatible");
    render(<Voices />);
    expect(await screen.findByRole("button", { name: "Selected narrator" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete My narrator" }));
    await waitFor(() => expect(accountStorage.getItem("nexus-reader-narrator-id")).toBeNull());
    expect(accountStorage.getItem("nexus-reader-tts-engine")).toBe("native");
    expect(screen.queryByText("My narrator")).not.toBeInTheDocument();
  });
  it("remounts private voice settings for an account change", async () => {
    render(<Voices />);
    await screen.findByText("My narrator");
    vi.mocked(voiceService.list).mockResolvedValue([]);
    act(() => activateAccountStorage(8));
    expect(screen.queryByText("My narrator")).not.toBeInTheDocument();
    expect(accountStorage.getItem("nexus-reader-narrator-id")).toBeNull();
    await waitFor(() => expect(voiceService.list).toHaveBeenCalledTimes(2));
  });
  it("loads the account default on a new device and preserves it on a failed change", async()=>{
    vi.mocked(voiceService.getDefault).mockResolvedValue({voice_profile_id:9,revision:4});
    vi.mocked(voiceService.setDefault).mockRejectedValue(new Error("conflict"));
    render(<Voices />);
    expect(await screen.findByRole("button",{name:"Selected narrator"})).toBeInTheDocument();
    expect(accountStorage.getItem("nexus-reader-narrator-id")).toBe("9");
    fireEvent.click(screen.getByRole("button",{name:"Selected narrator"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
    expect(accountStorage.getItem("nexus-reader-narrator-id")).toBe("9");
  });
  it("adopts a ready narrator selected before server defaults were introduced",async()=>{
    accountStorage.setItem("nexus-reader-narrator-id","9");
    vi.mocked(voiceService.getDefault).mockResolvedValue({voice_profile_id:null,revision:0});
    render(<Voices />);
    expect(await screen.findByRole("button",{name:"Selected narrator"})).toBeInTheDocument();
    expect(voiceService.setDefault).toHaveBeenCalledWith(9,0);
  });
  it("respects an explicit server reset instead of restoring an old device choice",async()=>{
    accountStorage.setItem("nexus-reader-narrator-id","9");
    vi.mocked(voiceService.getDefault).mockResolvedValue({voice_profile_id:null,revision:3});
    render(<Voices />);
    expect(await screen.findByRole("button",{name:"Use as narrator"})).toBeInTheDocument();
    expect(accountStorage.getItem("nexus-reader-narrator-id")).toBeNull();
    expect(voiceService.setDefault).not.toHaveBeenCalled();
  });
});
