import { describe, expect, expectTypeOf, it } from "vitest";
import type { ApiOperations } from "../generated/api";
import { usdToMicros, usageUsd, type ProviderReconciliation, type ProviderRequestsPage } from "./providerUsageService";
describe("exact provider billing amounts", () => {
  it("uses the generated server request and response contracts", () => {
    expectTypeOf<ProviderReconciliation>().toEqualTypeOf<ApiOperations["POST /reader/providers/{provider_id}/requests/{request_key}/reconcile"]["request"]>();
    expectTypeOf<ProviderRequestsPage>().toEqualTypeOf<ApiOperations["GET /reader/providers/{provider_id}/requests"]["response"]>();
  });
  it("requires an explicit amount while accepting verified zero and micro charges", () => {
    expect(usdToMicros("")).toBeNull(); expect(usdToMicros("0")).toBe(0); expect(usdToMicros("0.000001")).toBe(1);
    expect(usdToMicros("12.345678")).toBe(12_345_678); expect(usdToMicros("100000")).toBe(100_000_000_000);
    expect(usageUsd(1)).toBe("$0.000001");
  });
  it("rejects negative, rounded, exponential and oversized entries instead of guessing billing", () => {
    for (const value of ["-1", "1e3", "0.0000001", "100000.000001", "NaN", "abc", "1,20"]) expect(usdToMicros(value)).toBeNull();
  });
});
