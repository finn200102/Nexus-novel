import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProviderUsageLedger from "./ProviderUsageLedger";
import { providerUsageService, type ProviderRequest, type ProviderRequestsPage } from "../../services/providerUsageService";
import { accountStorage, activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/providerUsageService", async original => ({ ...await original<typeof import("../../services/providerUsageService")>(), providerUsageService: { list: vi.fn(), reconcile: vi.fn() } }));
const key = "11111111-1111-4111-8111-111111111111";
const row = (status: ProviderRequest["status"] = "unknown"): ProviderRequest => ({ request_key: key, provider_id: 3, revision: 4, status, reserved_microusd: 1, actual_microusd: null, input_tokens: null, output_tokens: null, model_snapshot: { kind: "openai_compatible", model: "original-model", base_url: "https://example.test/v1", input_price: "0.15", output_price: "0.60" }, created_at: "2026-10-16T09:00:00Z", expires_at: null, resolved_at: null, can_reconcile: status === "unknown" || status === "legacy_unknown", translation_job_id: 8, translation_block_index: 2 });
const page = (): ProviderRequestsPage => ({ items: [row()], total: 1, offset: 0, limit: 20, accounting: { budget_microusd: 1000000, used_microusd: 0, reserved_microusd: 1 } });
const refresh = vi.fn(async () => {});
const mount = () => render(<ProviderUsageLedger providerId={3} providerName="Private provider" onChanged={refresh} />);
async function review(amount = "0") {
  fireEvent.click(await screen.findByRole("button", { name: `Reconcile request ${key}` }));
  fireEvent.change(screen.getByLabelText("Verified actual charge (USD)"), { target: { value: amount } });
  fireEvent.click(screen.getByRole("checkbox", { name: /I checked this amount/ }));
  fireEvent.click(screen.getByRole("button", { name: "Review reconciliation" }));
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(1); vi.mocked(providerUsageService.list).mockResolvedValue(page()); vi.mocked(providerUsageService.reconcile).mockResolvedValue({ item: { ...row(), status: "reconciled", can_reconcile: false, actual_microusd: 0 }, accounting: { ...page().accounting, reserved_microusd: 0 } }); });
describe("private provider request accounting", () => {
  it("shows portrait image pricing instead of unrelated text token prices",async()=>{
    vi.mocked(providerUsageService.list).mockResolvedValue({...page(),items:[{...row(),purpose:"guide_portrait",translation_job_id:null,model_snapshot:{...row().model_snapshot,image_model:"reviewed-image-model",image_price_microusd:20001}}]});mount();
    expect(await screen.findByText("Private portrait")).toBeVisible();expect(screen.getByText(/Original model: reviewed-image-model/)).toBeVisible();expect(screen.getByText("Original maximum price per image: $0.020001")).toBeVisible();expect(screen.queryByText(/Original price per million tokens/)).not.toBeInTheDocument();expect(screen.queryByText(/Usage: input/)).not.toBeInTheDocument();
  });
  it("shows original prices and tiny reservations, pages exact records and blocks in-flight settlement", async () => {
    vi.mocked(providerUsageService.list).mockResolvedValue({ ...page(), total: 21, items: [row("pending")] }); mount();
    expect(await screen.findByText(/Reserved \$0.000001/)).toBeInTheDocument(); expect(screen.getByText(/Original model: original-model/)).toBeInTheDocument();
    expect(screen.getByText(/Original price per million tokens/)).toHaveTextContent("$0.15"); expect(screen.queryByRole("button", { name: `Reconcile request ${key}` })).not.toBeInTheDocument();
    expect(screen.getByText(/may still be in flight/)).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Next requests" }));
    await waitFor(() => expect(providerUsageService.list).toHaveBeenCalledWith(3, 20, 20)); expect(providerUsageService.reconcile).not.toHaveBeenCalled();
  });
  it.each(["0", null])("keeps reconciled legacy pricing unknown when the original price is %s", async price => {
    const legacy = { ...row("reconciled"), model_snapshot: { ...row().model_snapshot, kind: "legacy_unknown", input_price: price, output_price: price } };
    vi.mocked(providerUsageService.list).mockResolvedValue({ ...page(), items: [legacy] }); mount();
    expect(await screen.findByText("Original pricing is unknown for this legacy reservation.")).toBeInTheDocument();
    expect(screen.queryByText(/Original price per million tokens/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: `Reconcile request ${key}` })).not.toBeInTheDocument();
  });
  it("requires billing verification and a separate review before recording a verified zero", async () => {
    mount(); fireEvent.click(await screen.findByRole("button", { name: `Reconcile request ${key}` }));
    expect(screen.getByRole("button", { name: "Review reconciliation" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Verified actual charge (USD)"), { target: { value: "0" } }); expect(screen.getByRole("button", { name: "Review reconciliation" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I checked this amount/ })); fireEvent.click(screen.getByRole("button", { name: "Review reconciliation" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm provider billing" }); expect(dialog).toHaveTextContent("$0.000000"); expect(providerUsageService.reconcile).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm reconciliation" }));
    await waitFor(() => expect(providerUsageService.reconcile).toHaveBeenCalledWith(3, key, { expected_revision: 4, operation_id: expect.any(String), actual_microusd: 0 }));
    await screen.findByText(/Reconciliation confirmed/); expect(refresh).toHaveBeenCalledOnce(); expect(accountStorage.getItem("provider-reconciliation:3")).toBeNull();
  });
  it("retains only intent across reload and replays the same operation after a lost acknowledgement", async () => {
    vi.mocked(providerUsageService.reconcile).mockRejectedValueOnce(new Error("lost acknowledgement")); const first = mount(); await review("0.123456"); fireEvent.click(screen.getByRole("button", { name: "Confirm reconciliation" }));
    await waitFor(() => expect(providerUsageService.reconcile).toHaveBeenCalledOnce()); const original = vi.mocked(providerUsageService.reconcile).mock.calls[0];
    const stored = accountStorage.getItem("provider-reconciliation:3")!; expect(stored).toContain(original[2].operation_id); expect(stored).not.toMatch(/original-model|base_url|model_snapshot|prompt|api_key/);
    first.unmount(); mount(); fireEvent.click(await screen.findByRole("button", { name: "Review unconfirmed reconciliation" })); fireEvent.click(screen.getByRole("button", { name: "Retry same reconciliation" }));
    await screen.findByText(/Reconciliation confirmed/); expect(vi.mocked(providerUsageService.reconcile).mock.calls[1]).toEqual(original);
  });
  it("keeps all settlements blocked through the authoritative post-acknowledgement refresh", async () => {
    const current = deferred<ProviderRequestsPage>(); mount(); await review(); vi.mocked(providerUsageService.list).mockReturnValueOnce(current.promise);
    fireEvent.click(screen.getByRole("button", { name: "Confirm reconciliation" })); await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Refresh reconciled accounting" })).toBeDisabled(); expect(screen.getByRole("button", { name: `Reconcile request ${key}` })).toBeDisabled();
    await act(async () => current.resolve({ ...page(), items: [{ ...row(), status: "reconciled", can_reconcile: false }], accounting: { budget_microusd: 2000000, used_microusd: 123, reserved_microusd: 0 } }));
    expect(await screen.findByText(/Budget \$2.000000 · used \$0.000123/)).toBeInTheDocument(); expect(screen.queryByRole("button", { name: `Reconcile request ${key}` })).not.toBeInTheDocument();
  });
  it("refreshes after a revision conflict and requires a new review rather than retrying blindly", async () => {
    vi.mocked(providerUsageService.reconcile).mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { detail: { message: "This request changed on another device." } } } });
    mount(); await review(); fireEvent.click(screen.getByRole("button", { name: "Confirm reconciliation" }));
    expect(await screen.findByText("This request changed on another device.")).toBeInTheDocument(); await waitFor(() => expect(providerUsageService.list).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "Retry same reconciliation" })).not.toBeInTheDocument(); expect(providerUsageService.reconcile).toHaveBeenCalledOnce(); expect(accountStorage.getItem("provider-reconciliation:3")).toBeNull();
  });
  it("ignores late private responses and hides pending intents when the account changes", async () => {
    const late = deferred<ProviderRequestsPage>(); vi.mocked(providerUsageService.list).mockReturnValueOnce(late.promise); mount();
    vi.mocked(providerUsageService.list).mockResolvedValue({ ...page(), total: 0, items: [] }); act(() => activateAccountStorage(2)); await act(async () => late.resolve(page()));
    expect(await screen.findByText("No provider requests have been recorded.")).toBeInTheDocument(); expect(screen.queryByText(/original-model/)).not.toBeInTheDocument(); expect(providerUsageService.reconcile).not.toHaveBeenCalled();
  });
  it("refreshes accounting after a confirmed write without resubmitting when that refresh failed", async () => {
    mount(); await review(); vi.mocked(providerUsageService.list).mockRejectedValueOnce(new Error("refresh unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm reconciliation" }));
    await screen.findByText("Reconciliation was confirmed. Refresh accounting before making another change.");
    expect(JSON.parse(accountStorage.getItem("provider-reconciliation:3")!).acknowledged).toBe(true);
    expect(screen.getByRole("button", { name: `Reconcile request ${key}` })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh reconciled accounting" }));
    await screen.findByText(/Reconciliation confirmed/); expect(providerUsageService.reconcile).toHaveBeenCalledOnce();
    expect(accountStorage.getItem("provider-reconciliation:3")).toBeNull();
  });
  it("never refreshes another account with a late successful settlement", async () => {
    const late = deferred<Awaited<ReturnType<typeof providerUsageService.reconcile>>>();
    vi.mocked(providerUsageService.reconcile).mockReturnValueOnce(late.promise); mount(); await review();
    fireEvent.click(screen.getByRole("button", { name: "Confirm reconciliation" })); await waitFor(() => expect(providerUsageService.reconcile).toHaveBeenCalledOnce());
    vi.mocked(providerUsageService.list).mockResolvedValue({ ...page(), items: [], total: 0 }); act(() => activateAccountStorage(2));
    await act(async () => late.resolve({ item: row("reconciled"), accounting: page().accounting }));
    expect(await screen.findByText("No provider requests have been recorded.")).toBeInTheDocument(); expect(refresh).not.toHaveBeenCalled();
    expect(accountStorage.getItem("provider-reconciliation:3")).toBeNull();
    act(() => activateAccountStorage(1)); expect(await screen.findByRole("button", { name: "Review unconfirmed reconciliation" })).toBeInTheDocument();
  });
  it("refuses submission if the stable operation cannot be retained for reload recovery", async () => {
    mount(); await review(); const storage = vi.spyOn(accountStorage, "setItem").mockImplementationOnce(() => { throw new Error("storage blocked"); });
    fireEvent.click(screen.getByRole("button", { name: "Confirm reconciliation" }));
    expect(await screen.findAllByText(/Nothing was submitted/)).not.toHaveLength(0); expect(providerUsageService.reconcile).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it("adopts another tab's recorded operation instead of overwriting it", async () => {
    mount(); await review(); const recorded = { request_key: key, input: { expected_revision: 4, operation_id: "another-tab-operation", actual_microusd: 500 } };
    accountStorage.setItem("provider-reconciliation:3", JSON.stringify(recorded)); fireEvent.click(screen.getByRole("button", { name: "Confirm reconciliation" }));
    expect(await screen.findByText(/Another reconciliation is recorded/)).toBeInTheDocument(); expect(providerUsageService.reconcile).not.toHaveBeenCalled();
    expect(JSON.parse(accountStorage.getItem("provider-reconciliation:3")!)).toEqual(recorded);
  });

});
