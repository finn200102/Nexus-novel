import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PassageRevision from "./PassageRevision";
import apiClient from "../../services/apiClient";
import { readerToolsService, type ReaderProvider } from "../../services/readerToolsService";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/apiClient", () => ({ default: { post: vi.fn() }, getUserFacingError: (_: unknown, fallback: string) => fallback }));
vi.mock("../../services/readerToolsService", () => ({ readerToolsService: { permission: vi.fn(), setTranslationPermission: vi.fn() } }));
const provider: ReaderProvider = { id: 5, name: "Premium", model: "configured-model", kind: "anthropic", base_url: "https://example.invalid", budget_usd: 5, used_usd: 1, reserved_usd: .5 };
const props = { novelId: 1, chapter: 2, language: "de", draft: "Reviewed economy draft.", providers: [provider],
  anchor: { content_version: "original-version", block_id: "original-block", text_offset: 7, text_length: 2, quote: "😀" } };
const permission = { translation: null, companion: false, ao3_consent: false, is_ao3: true, local: false };
const open = () => fireEvent.click(screen.getByText("Revise this draft with a chosen provider"));
const choose = () => fireEvent.change(screen.getByRole("combobox", { name: "Revision provider" }), { target: { value: "5" } });
describe("explicit passage revision", () => {
  beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(1); vi.mocked(readerToolsService.permission).mockResolvedValue(permission); });
  it("requires a separate provider decision and permission, then revises the reviewed draft only", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { translation: "<em>literal revised prose</em>", charged_usd: .03 } });
    render(<PassageRevision {...props} />); open();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Revise reviewed draft" })).toBeDisabled(); choose();
    await waitFor(() => expect(readerToolsService.permission).toHaveBeenCalledWith(1, 5));
    const allow = await screen.findByRole("switch", { name: "Allow sending this AO3 passage and draft to the revision provider" });
    expect(screen.getByRole("button", { name: "Revise reviewed draft" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Passage draft to revise"), { target: { value: "Edited draft" } });
    fireEvent.click(allow);
    fireEvent.click(screen.getByRole("button", { name: "Revise reviewed draft" }));
    expect(await screen.findByText("<em>literal revised prose</em>")).toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledWith("/reader/translations/1/2/passage-revision", { ...props.anchor, draft: "Edited draft", provider_id: 5, language: "de", external_consent: true, ao3_consent: true }, { timeout: 130_000 });
    expect(screen.queryByText("literal revised prose", { selector: "em" })).not.toBeInTheDocument();
  });
  it("retains blocked permissions until the explicit grant and preserves companion choice", async () => {
    vi.mocked(readerToolsService.permission).mockResolvedValue({ ...permission, translation: false });
    vi.mocked(readerToolsService.setTranslationPermission).mockResolvedValue({ ...permission, translation: true, ao3_consent: true });
    render(<PassageRevision {...props} />); open(); choose();
    fireEvent.click(await screen.findByRole("switch", { name: "Allow sending this AO3 passage and draft to the revision provider" }));
    expect(screen.getByRole("button", { name: "Revise reviewed draft" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Allow translation for this story and revision provider" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Revise reviewed draft" })).toBeEnabled());
    expect(readerToolsService.setTranslationPermission).toHaveBeenCalledWith(1, 5, { translation: true, ao3_consent: true });
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("keeps oversized drafts editable and excludes non-conversational local translators", async () => {
    render(<PassageRevision {...props} providers={[{ ...provider, kind: "local_translation" }]} draft={"x".repeat(6001)} />); open();
    expect(screen.getByLabelText("Passage draft to revise")).toHaveValue("x".repeat(6001));
    expect(screen.queryByRole("option", { name: "Premium · configured-model" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revise reviewed draft" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("discards a delayed result after the active account changes", async () => {
    vi.mocked(readerToolsService.permission).mockResolvedValue({ ...permission, translation: true, ao3_consent: true });
    let finish!: (value: never) => void;
    vi.mocked(apiClient.post).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<PassageRevision {...props} />); open(); choose();
    await waitFor(() => expect(screen.getByRole("button", { name: "Revise reviewed draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Revise reviewed draft" }));
    await act(async () => { activateAccountStorage(2); finish({ data: { translation: "Previous account response", charged_usd: .01 } } as never); });
    expect(screen.queryByText("Previous account response")).not.toBeInTheDocument();
  });
});
