import apiClient from "./apiClient";
import type { ReaderProviderAccountingResponse, ReaderProviderReconcileInput, ReaderProviderReconcileResponse, ReaderProviderRequestResponse, ReaderProviderRequestsPage } from "../generated/api";
export type ProviderRequest = ReaderProviderRequestResponse;
export type ProviderRequestStatus = ProviderRequest["status"];
export type ProviderAccounting = ReaderProviderAccountingResponse;
export type ProviderRequestsPage = ReaderProviderRequestsPage;
export type ProviderReconciliation = ReaderProviderReconcileInput;
export type ProviderReconciliationResponse = ReaderProviderReconcileResponse;
export const providerUsageService = {
  async list(providerId: number, offset = 0, limit = 20): Promise<ProviderRequestsPage> {
    return (await apiClient.get(`/reader/providers/${providerId}/requests`, { params: { offset, limit } })).data;
  },
  async reconcile(providerId: number, key: string, input: ProviderReconciliation): Promise<ProviderReconciliationResponse> {
    return (await apiClient.post(`/reader/providers/${providerId}/requests/${encodeURIComponent(key)}/reconcile`, input)).data;
  },
};
/** Parse a billing amount exactly, without floating-point rounding or implicit zero. */
export function usdToMicros(value: string): number | null {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(value.trim())) return null;
  const [whole, fraction = ""] = value.trim().split(".");
  const micros = Number(whole) * 1_000_000 + Number(fraction.padEnd(6, "0"));
  return Number.isSafeInteger(micros) && micros <= 100_000_000_000 ? micros : null;
}
export const usageUsd = (value: number) => `$${(value / 1_000_000).toFixed(6)}`;
