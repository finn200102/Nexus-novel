import type { ExpectedChapterIdentity } from "../../services/chapterIdentity";
import type { ChapterDocument } from "./chapterDocument";

export interface PassageAnchor extends Partial<ExpectedChapterIdentity> {
  content_version: string;
  block_id: string;
  text_offset: number;
  text_length: number;
  quote: string;
}

/** Capture exact original text, never guess offsets in translated or altered DOM. */
export function capturePassage(container: HTMLElement, source: ChapterDocument): PassageAnchor | null {
  const selection = window.getSelection();
  if (!selection?.rangeCount || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) return null;
  const element = range.startContainer.nodeType === Node.ELEMENT_NODE
    ? range.startContainer as Element : range.startContainer.parentElement;
  const block = element?.closest<HTMLElement>("[data-block-id]");
  if (!block || !container.contains(block) || !block.contains(range.endContainer)) return null;
  const original = source.blocks.find(row => row.id === block.dataset.blockId);
  if (!original || block.textContent !== original.text) return null;
  const before = document.createRange();
  before.selectNodeContents(block); before.setEnd(range.startContainer, range.startOffset);
  const quote = range.toString(), offset = before.toString().length;
  if (!quote.trim() || Array.from(quote).length > 3000 || new TextEncoder().encode(quote).length > 12000) return null;
  if (original.text.slice(offset, offset + quote.length) !== quote || /^[\uDC00-\uDFFF]/.test(quote) || /[\uD800-\uDBFF]$/.test(quote)) return null;
  return { content_version: source.content_version, block_id: original.id, text_offset: offset, text_length: quote.length, quote };
}
