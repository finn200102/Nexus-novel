import { describe, expectTypeOf, it } from "vitest";
import type { ApiOperations, Chapter, ReadingAnnotationCreate, ReadingAnnotationResponse, ReadingProgressUpdate } from "../generated/api";
import { chapterService } from "./chapterService";
import type { ChapterContentResponse, ReaderChapterContent } from "./chapterContracts";
import type { ChapterDocument } from "../components/reader/chapterDocument";
import type { ReadingAnnotation, RecapData } from "../components/reader/ReaderPanels";

describe("generated chapter contracts", () => {
  it("keeps actual content wire contracts separate from validated reader documents", () => {
    expectTypeOf<ChapterContentResponse>().toEqualTypeOf<ApiOperations["GET /chapter/content/library/{library_id}/{novel_id}/{chapter_number}"]["response"]>();
    expectTypeOf<ReaderChapterContent["document"]>().toEqualTypeOf<ChapterDocument | undefined>();
    expectTypeOf<Awaited<ReturnType<typeof chapterService.getChapters>>>().toEqualTypeOf<Chapter[]>();
  });
  it("uses generated write bodies without making defaulted fields compulsory", () => {
    expectTypeOf<{ chapter_number: number }>().toExtend<ReadingProgressUpdate>();
    expectTypeOf<Parameters<typeof chapterService.createReadingAnnotation>[1]>().toEqualTypeOf<ReadingAnnotationCreate>();
    expectTypeOf<ReadingProgressUpdate>().toEqualTypeOf<ApiOperations["PUT /chapter/progress/{novel_id}"]["request"]>();
    expectTypeOf<Awaited<ReturnType<typeof chapterService.createReadingAnnotation>>>().toEqualTypeOf<ReadingAnnotationResponse>();
  });
  it("derives presentation fields without requiring unrelated response metadata", () => {
    expectTypeOf<{ id: number; chapter_number: number; annotation_type: string; position: number; percent: number }>().toExtend<ReadingAnnotation>();
    expectTypeOf<RecapData["chapters"][number]["title"]>().toEqualTypeOf<string | null>();
  });
});
