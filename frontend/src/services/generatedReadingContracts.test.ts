import { describe, expectTypeOf, it } from "vitest";
import type { ApiOperations, ReadingJournalPageResponse, ReadingRunProgressResponse, ReadingRunStateResponse, StatsSummaryResponse } from "../generated/api";
import type { ReadingGoalWrite, StatsSummary } from "./readingStatsService";
import type { ReadingJournalPage, ReadingRunChange, ReadingRunProgress, ReadingRunsPage } from "./readingJournalService";
import type { PreferenceResponse, PreferenceValues } from "./readerPreferenceSync";

describe("generated reading contracts", () => {
  it("uses server DTOs for summaries and sparse historical snapshots", () => {
    expectTypeOf<StatsSummary>().toEqualTypeOf<StatsSummaryResponse>();
    expectTypeOf<ReadingRunProgress>().toEqualTypeOf<ReadingRunProgressResponse>();
    expectTypeOf<ReadingRunsPage>().toEqualTypeOf<ReadingRunStateResponse>();
    expectTypeOf<ReadingJournalPage>().toEqualTypeOf<ReadingJournalPageResponse>();
    expectTypeOf<Record<string, never>>().toExtend<ReadingRunProgress>();
    expectTypeOf<{ chapter_number: number; percent: null }>().toExtend<ReadingRunProgress>();
  });
  it("keeps explicit goal and run writes compatible with the generated operations", () => {
    expectTypeOf<ReadingGoalWrite>().toExtend<ApiOperations["PUT /stats/goals/{year}"]["request"]>();
    expectTypeOf<ReadingRunChange>().toEqualTypeOf<ApiOperations["POST /reading/stories/{novel_id}/runs/drop"]["request"]>();
  });
  it("retains local numeric typography controls and the validated scope refinement", () => {
    expectTypeOf<{ typography: { lineHeight: number }; layout: "paged" }>().toExtend<PreferenceValues>();
    expectTypeOf<PreferenceResponse["scope"]>().toEqualTypeOf<"global" | `story:${number}`>();
    expectTypeOf<PreferenceValues["layout"]>().toEqualTypeOf<"scroll" | "paged" | undefined>();
  });
});
