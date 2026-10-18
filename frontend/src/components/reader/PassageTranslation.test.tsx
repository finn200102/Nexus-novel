import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PassageTranslation from "./PassageTranslation";
import apiClient from "../../services/apiClient";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/apiClient", () => ({ default: { post: vi.fn() }, getUserFacingError: (_: unknown, fallback: string) => fallback }));
const props = { novelId: 1, chapter: 2, providerId: 3, language: "de", consent: false, ao3Consent: false, disabled: false,
  anchor: { content_version: "original-version", block_id: "original-block", text_offset: 7, text_length: 2, quote: "😀" } };
describe("selected passage translation", () => {
  beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(1); });
  it("sends only exact selection on user action and renders response as literal text", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { translation: "<script>literal text</script>", charged_usd: .01 } });
    render(<PassageTranslation {...props} />);
    expect(apiClient.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Translate this passage" }));
    expect(await screen.findByText("<script>literal text</script>", { selector: "p" })).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(apiClient.post).toHaveBeenCalledWith("/reader/translations/1/2/passage-preview", {
      ...props.anchor, provider_id: 3, language: "de", external_consent: false, ao3_consent: false,
    }, { timeout: 130_000 });
  });
  it("does not send without an exact anchor or permission", () => {
    const view = render(<PassageTranslation {...props} disabled />);
    expect(screen.getByRole("button", { name: "Translate this passage" })).toBeDisabled();
    view.rerender(<PassageTranslation {...props} anchor={null} />);
    expect(screen.queryByRole("button", { name: "Translate this passage" })).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("discards delayed results after provider changes or account switches", async () => {
    let finish!: (value: never) => void;
    vi.mocked(apiClient.post).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const view = render(<PassageTranslation {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Translate this passage" }));
    view.rerender(<PassageTranslation {...props} providerId={4} />);
    await act(async () => { finish({ data: { translation: "old provider secret", charged_usd: 0 } } as never); });
    expect(screen.queryByText("old provider secret")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Translate this passage" }));
    await act(async () => { activateAccountStorage(2); finish({ data: { translation: "old account secret", charged_usd: 0 } } as never); });
    expect(screen.queryByText("old account secret")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Translate this passage" })).not.toBeInTheDocument();
    expect(screen.queryByText("😀")).not.toBeInTheDocument();
  });
});
