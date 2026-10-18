import { describe, expect, it } from "vitest";
import { imageReadiness, offlineReadinessLabel } from "./imageReadiness";
import type { ChapterDocument } from "./chapterDocument";

const document: ChapterDocument = { schema_version: 1, source_format: "html", content_version: "fixture", plain_text: "Story", blocks: [
  { id: "art", kind: "p", text: "Story", html: '<p>Story<img src="data:image/png;base64,AA==" alt="Map"></p>' },
] };
describe("offline illustration readiness", () => {
  it("reports stored legacy illustrations without claiming missing originals are ready", () => {
    expect(imageReadiness(document)).toEqual({ ready: 1, total: 1, missing: 0 });
    expect(offlineReadinessLabel(document)).toBe("text and 1 image ready offline");
    expect(offlineReadinessLabel()).toBe("text ready offline");
  });
  it("retains a partial source download's missing-image count", () => {
    const partial = { ...document, image_assets: { total: 3, ready: 1, missing: 2, limited: 1, bytes: 12, failures: { prohibited_host: 1, asset_limit: 1 } } };
    expect(imageReadiness(partial)).toEqual({ ready: 1, total: 3, missing: 2 });
    expect(offlineReadinessLabel(partial)).toBe("text ready · 1 of 3 images ready");
  });
  it("does not claim external, temporary or invalid legacy images are stored", () => {
    const legacy = { ...document, blocks: [{ ...document.blocks[0], html: '<p><img src="https://example.org/map.png"><img src="blob:expired"><img src="data:image/svg+xml;base64,AA=="><img data-src="data:image/png;base64,AA=="><img src="data:image/png;base64,invalid!"><img src="data:image/png;base64,AA=="></p>' }] };
    expect(imageReadiness(legacy)).toEqual({ ready: 1, total: 6, missing: 5 });
  });
});
