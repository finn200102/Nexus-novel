import { describe, expect, it } from "vitest";
import { splitTextForSynthesis, TTS_PROVIDER_PRESETS } from "../../src/services/ttsService";

describe("splitTextForSynthesis", () => {
  it("keeps ordinary sentences together while bounding provider request sizes", () => {
    const chunks = splitTextForSynthesis("One sentence. Two sentence. Three sentence.", 28);

    expect(chunks).toEqual(["One sentence. Two sentence.", "Three sentence."]);
    expect(chunks.every((chunk) => chunk.length <= 28)).toBe(true);
  });

  it("splits a single oversized sentence so an audio job always advances", () => {
    const chunks = splitTextForSynthesis("abcdefghijkl", 5);

    expect(chunks).toEqual(["abcde", "fghij", "kl"]);
  });

  it("returns no jobs for empty chapter text", () => {
    expect(splitTextForSynthesis("  \n ")).toEqual([]);
  });

  it("exposes the supported local narrator presets without hiding Qwen's experimental state", () => {
    expect(TTS_PROVIDER_PRESETS.map((provider) => provider.id)).toEqual([
      "kokoro_mps",
      "qwen3_mlx_4bit",
      "chatterbox_turbo_mlx",
      "spark_tts_mlx",
      "custom",
    ]);
    expect(TTS_PROVIDER_PRESETS.find((provider) => provider.id === "qwen3_mlx_4bit")?.label).toContain("experimental");
  });
});
