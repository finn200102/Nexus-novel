/// <reference lib="es2022.intl" />
import { quoteLocator, type TextLocator } from "./chapterDocument";

export interface SearchBlock { id: string; text: string }
export interface ChapterMatch { locator: TextLocator; blockIndex: number; textOffset: number; endBlockIndex: number; endOffset: number; excerpt: string }

function folded(value: string, caseSensitive: boolean) {
  let text = "";
  const starts: number[] = [], ends: number[] = [];
  if (!/[\u0080-\uFFFF]/.test(value)) {
    const raw = caseSensitive ? value : value.toLowerCase();
    const parts: string[] = [];
    for (let index = 0; index < raw.length; index++) {
      const char = raw[index];
      if (/\s/.test(char)) {
        if (parts[parts.length - 1] === " ") { ends[ends.length - 1] = index + 1; continue; }
        parts.push(" ");
      } else parts.push(char);
      starts.push(index); ends.push(index + 1);
    }
    return { text: parts.join(""), starts, ends };
  }
  function* fallbackSegments() {
    const pattern = /[^\p{M}]\p{M}*|\p{M}+/gu;
    for (const match of value.matchAll(pattern)) yield { segment: match[0], index: match.index! };
  }
  const segments = typeof Intl.Segmenter === "function" ? new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(value) : fallbackSegments();
  for (const part of segments) {
    const end = part.index + part.segment.length;
    const normalized = part.segment.normalize("NFC");
    const lower = caseSensitive ? normalized : normalized.toLowerCase();
    for (const char of lower) {
      if (/\s/u.test(char)) {
        if (text.endsWith(" ")) { ends[ends.length - 1] = end; continue; }
        text += " "; starts.push(part.index); ends.push(end);
      } else {
        text += char;
        for (let unit = 0; unit < char.length; unit++) { starts.push(part.index); ends.push(end); }
      }
    }
  }
  return { text, starts, ends };
}

/** Literal, Unicode-normalized search with original UTF-16 offsets preserved. */
export function prepareChapterSearch(blocks: SearchBlock[], caseSensitive = false) {
  const offsets: number[] = [];
  let corpus = "";
  for (const block of blocks) { offsets.push(corpus.length); corpus += block.text + "\n\n"; }
  const source = folded(corpus, caseSensitive);
  return (query: string, limit = 200): { matches: ChapterMatch[]; truncated: boolean } => {
  const needle = folded(query.trim(), caseSensitive).text.trim(), matches: ChapterMatch[] = [];
  if (!needle || limit < 1) return { matches: [], truncated: false };
  let at = source.text.indexOf(needle), blockIndex = 0;
  while (at >= 0) {
    if (matches.length >= limit) return { matches, truncated: true };
    const rawStart = source.starts[at], rawEnd = source.ends[at + needle.length - 1];
    while (blockIndex + 1 < offsets.length && offsets[blockIndex + 1] <= rawStart) blockIndex++;
    const textOffset = rawStart - offsets[blockIndex];
    let endBlockIndex = blockIndex;
    while (endBlockIndex + 1 < offsets.length && offsets[endBlockIndex + 1] < rawEnd) endBlockIndex++;
    matches.push({ blockIndex, textOffset, endBlockIndex, endOffset: Math.min(blocks[endBlockIndex].text.length, rawEnd - offsets[endBlockIndex]), locator: quoteLocator(blocks, blockIndex, textOffset),
      excerpt: `${rawStart > 60 ? "…" : ""}${corpus.slice(Math.max(0, rawStart - 60), Math.min(corpus.length, rawEnd + 100)).replace(/\s+/g, " ")}${rawEnd + 100 < corpus.length ? "…" : ""}` });
    at = source.text.indexOf(needle, at + needle.length);
  }
  return { matches, truncated: false };
  };
}

export const searchChapter = (blocks: SearchBlock[], query: string, caseSensitive = false, limit = 200) =>
  prepareChapterSearch(blocks, caseSensitive)(query, limit);

/** Native selection gives every browser an accessible visible match highlight. */
export function selectChapterMatch(container: HTMLElement, match: ChapterMatch) {
  const blocks = Array.from(container.querySelectorAll<HTMLElement>("[data-block-id]"));
  if (blocks[match.blockIndex]?.dataset.blockId !== match.locator.blockId) return;
  const point = (element: HTMLElement | undefined, offset: number): [Node, number] | undefined => {
    if (!element) return;
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let remaining = offset;
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      if (remaining <= node.length) return [node, remaining];
      remaining -= node.length;
    }
  };
  const start = point(blocks[match.blockIndex], match.textOffset), end = point(blocks[match.endBlockIndex], match.endOffset);
  if (!start || !end) return;
  const range = document.createRange(); range.setStart(...start); range.setEnd(...end);
  const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range);
}
