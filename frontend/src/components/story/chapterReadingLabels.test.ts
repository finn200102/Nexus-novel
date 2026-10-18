import { describe, expect, it } from "vitest";
import { completedChaptersLabel, readingPlaceLabel } from "./chapterReadingLabels";
import type { ChapterReadingSummary } from "../../services/chapterService";
const summary = { novel_id:11,reading_run_key:null,revision:0,total_chapters:2001,followed_total:2001,completed_chapters:1,followed_completed_chapters:1,completion_basis:"recorded_checkpoints",completed_reading:false,current:{chapter_id:9,chapter_number:20007,ordinal:2,followed_ordinal:2,percent:40},next_unread_chapter_id:9,next_unread_chapter_number:20007,categories:["story"],categories_truncated:false } satisfies ChapterReadingSummary;
describe("chapter labels and recorded counts", () => {
  it("keeps a gapped source number separate from its ordinal and completed count", () => {
    expect(readingPlaceLabel(summary)).toBe("Current place: Chapter 20007 · 2 of 2001 in story · 40%");
    expect(completedChaptersLabel(summary)).toBe("1 of 2001 completed chapters recorded");
  });
  it.each([-2,0])("retains actual signed chapter %s", chapter_number => {
    expect(readingPlaceLabel({...summary,current:{...summary.current,chapter_number,ordinal:1}})).toContain(`Chapter ${chapter_number} · 1 of 2001`);
  });
  it("does not fabricate an ordinal when a source chapter was deleted", () => {
    expect(readingPlaceLabel({...summary,current:{...summary.current,chapter_id:null,ordinal:null}})).toContain("chapter no longer in the current list");
    expect(readingPlaceLabel({...summary,current:null})).toBe("No saved reading place");
  });
});
