import { describe, expect, it } from "vitest";
import { termNames } from "./termNames";

describe("termNames", () => {
  it("accepts strings and {name} objects, trims, and removes duplicates", () => {
    expect(termNames([" Gore ", { name: "gore" }, { name: "" }, null, "Magic"])).toEqual(["Gore", "gore", "Magic"]);
  });

  it("returns an empty list for missing input", () => {
    expect(termNames(undefined)).toEqual([]);
  });
});
