import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChapterBody from "./ChapterBody";
import type { ChapterDocument } from "./chapterDocument";

const document: ChapterDocument = { schema_version: 1, source_format: "html", content_version: "a".repeat(64), plain_text: "Story. Rich note.", blocks: [
  { id: "body", kind: "p", text: "Story.", html: "<p>Story.</p>" },
  { id: "note", kind: "p", text: "Rich note.", html: '<p>Rich <em>note</em>. <a href="https://example.org">Link</a></p>', role: "author_note", role_provenance: "source" },
] };

describe("rich author notes", () => {
  it("preserves rich markup and anchors while collapsing and revealing the note", () => {
    const { container } = render(<ChapterBody document={document} content={document.plain_text} authorNotes="collapsed" />);
    expect(container.querySelector('[data-block-id="note"] em')?.textContent).toBe("note");
    expect(screen.getByRole("link", { name: "Link" }).getAttribute("href")).toBe("https://example.org");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");
  });
  it("hides only notes and retains the story’s original block identity", () => {
    const { container } = render(<ChapterBody document={document} content={document.plain_text} authorNotes="hidden" />);
    expect(container.querySelector('[data-block-id="note"]')).toBeNull();
    expect(container.querySelector('[data-block-id="body"]')?.textContent).toBe("Story.");
  });
  it("keeps identical rich text nodes intact across parent renders", () => {
    const view = render(<ChapterBody document={document} content={document.plain_text} authorNotes="shown" />);
    const node = view.container.querySelector('[data-block-id="note"] p')!.firstChild;
    view.rerender(<ChapterBody document={{ ...document, blocks: document.blocks.map(block => ({ ...block })) }} content={document.plain_text} authorNotes="shown" />);
    expect(view.container.querySelector('[data-block-id="note"] p')!.firstChild).toBe(node);
  });
  it("recognizes a boundary note in older rich text without classifying a middle note marker", () => {
    const older: ChapterDocument = { ...document, blocks: [
      { id: "first", kind: "p", text: "A/N: Thanks.", html: "<p>A/N: Thanks.</p>" },
      { id: "story", kind: "p", text: "Story.", html: "<p>Story.</p>" },
      { id: "middle", kind: "p", text: "Note: a message in the plot.", html: "<p>Note: a message in the plot.</p>" },
      { id: "last", kind: "p", text: "The end.", html: "<p>The end.</p>" },
    ] };
    const { container } = render(<ChapterBody document={older} content={older.plain_text} authorNotes="hidden" />);
    expect(container.querySelector('[data-block-id="first"]')).toBeNull();
    expect(container.querySelector('[data-block-id="middle"]')).not.toBeNull();
  });
});
