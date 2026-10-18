import { describe, expect, it } from "vitest";
import { companionBoundary, initialCompanionBoundary } from "./companionBoundary";
describe("companion source boundaries", () => {
  it("preserves zero, negative and minimum source numbers without inventing chapter zero", () => {
    expect(initialCompanionBoundary(0)).toBe("-1"); expect(initialCompanionBoundary(-2)).toBe("-3"); expect(initialCompanionBoundary(-2147483648)).toBe("");
    expect(companionBoundary("0", 3)).toBe(0); expect(companionBoundary("-2", 0)).toBe(-2); expect(companionBoundary("-2147483648", -2147483648)).toBe(-2147483648);
    expect(companionBoundary("", -2)).toBeUndefined();
  });
  it.each(["0.5", "-2147483649", "2147483648", "NaN", "Infinity", "1"])("rejects malformed/future %s without widening the boundary", raw => expect(companionBoundary(raw, 0)).toBeNull());
});
