import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChapterBody from "./ChapterBody";
import type { ChapterDocument } from "./chapterDocument";

const src = "data:image/png;base64,aGVsbG8=";
const document: ChapterDocument = { schema_version: 1, source_format: "html", content_version: "a".repeat(64), plain_text: "Story", blocks: [
  { id: "picture", kind: "p", text: "Story", html: `<p>Story <img src="${src}" alt="Map of the island"></p>` },
  { id: "second", kind: "p", text: "", html: `<p><img src="${src}" alt="The lighthouse"></p>` },
] };

describe("chapter illustrations", () => {
  it("opens, zooms and navigates without bubbling into reader page turns", () => {
    const turn = vi.fn();
    const { container } = render(<div onClick={turn}><ChapterBody content="Story" authorNotes="shown" document={document} /></div>);
    const image = screen.getByRole("button", { name: "Open illustration: Map of the island" });
    const originalNode = container.querySelector('[data-block-id="picture"] p')!.firstChild;
    fireEvent.click(image);
    expect(turn).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Chapter illustration" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("img", { name: "Map of the island" }).style.width).toBe("150%");
    fireEvent.keyDown(screen.getByRole("button", { name: "Zoom in" }), { key: "ArrowRight" });
    expect(screen.getByRole("img", { name: "The lighthouse" }).style.width).toBe("100%");
    fireEvent.click(screen.getByRole("button", { name: "Close illustration" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(image).toBe(globalThis.document.activeElement);
    expect(container.querySelector('[data-block-id="picture"] p')!.firstChild).toBe(originalNode);
    expect(turn).not.toHaveBeenCalled();
  });
  it("supports keyboard activation, reports broken images and closes on source changes", () => {
    const view = render(<ChapterBody content="Story" authorNotes="shown" document={document} />);
    fireEvent.keyDown(screen.getByRole("button", { name: "Open illustration: Map of the island" }), { key: "Enter" });
    fireEvent.error(screen.getByRole("img", { name: "Map of the island" }));
    expect(screen.getByRole("status").textContent).toContain("could not be displayed");
    view.rerender(<ChapterBody content="Story" authorNotes="shown" document={{ ...document, content_version: "b".repeat(64) }} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("leaves linked and remote images alone and excludes hidden notes", () => {
    const view = render(<ChapterBody content="Story" authorNotes="hidden" document={{ ...document, blocks: [
      ...document.blocks,
      { id: "linked", kind: "p", text: "", html: `<a href="https://example.org"><img src="${src}" alt="Linked map"></a>` },
      { id: "remote", kind: "p", text: "", html: '<img src="https://example.org/map.png" alt="Remote map">' },
      { id: "note", kind: "p", text: "Note", html: `<img src="${src}" alt="Note illustration">`, role: "author_note" },
    ] }} />);
    expect(view.container.querySelector('img[alt="Linked map"]')?.getAttribute("role")).toBeNull();
    expect(view.container.querySelector('img[alt="Remote map"]')?.getAttribute("role")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open illustration: Map of the island" }));
    expect(screen.getByText("1 of 2 · Map of the island")).toBeTruthy();
  });
});
