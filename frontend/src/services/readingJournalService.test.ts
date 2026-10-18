import { afterEach, describe, expect, it, vi } from "vitest";
import { readingJournalOperationId } from "./readingJournalService";
describe("reading journal operation identity", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("uses browser UUIDs when available", () => {
    const randomUUID = vi.fn(() => "11111111-1111-4111-8111-111111111111"); vi.stubGlobal("crypto", { randomUUID }); expect(readingJournalOperationId()).toBe("11111111-1111-4111-8111-111111111111"); expect(randomUUID).toHaveBeenCalledOnce();
  });
  it("provides a valid random UUID on household HTTP origins lacking randomUUID", () => {
    const getRandomValues = vi.fn((value: Uint8Array) => { value.fill(0); return value; }); vi.stubGlobal("crypto", { getRandomValues }); expect(readingJournalOperationId()).toBe("00000000-0000-4000-8000-000000000000"); expect(getRandomValues).toHaveBeenCalledOnce();
  });
});
