export interface ChapterBlock {
  id: string;
  kind: string;
  html: string;
  text: string;
  role?: "author_note";
  role_provenance?: "source" | "heuristic";
}

export interface ChapterDocument {
  schema_version: 1;
  content_version: string;
  source_format: "text" | "html";
  blocks: ChapterBlock[];
  plain_text: string;
  image_assets?: { total: number; ready: number; missing: number; limited: number; bytes: number; failures: Record<string, number> };
}

export interface TextLocator {
  blockId?: string;
  textOffset?: number;
  textQuote?: string;
  quotePrefix?: string;
  quoteSuffix?: string;
}
export type AnchorResolution = { blockIndex: number; textOffset: number; method: "block" | "quote" }
  | { reason: "missing" | "ambiguous" };

export const normalizeAnchorText = (value: string) => value.replace(/\s+/g, " ").trim();
const safeSlice = (value: string, start: number, end?: number) => {
  let text = value.slice(start, end);
  if (/^[\uDC00-\uDFFF]/.test(text)) text = text.slice(1);
  if (/[\uD800-\uDBFF]$/.test(text)) text = text.slice(0, -1);
  return text;
};

/** Context includes neighboring blocks so repeated passages can be disambiguated. */
export function quoteLocator(blocks: { id: string; text: string }[], index: number, offset: number): TextLocator {
  const block = blocks[index];
  let at = Math.min(Math.max(Math.floor(offset), 0), block.text.length);
  if (at && /^[\uDC00-\uDFFF]/.test(block.text.slice(at))) at -= 1;
  const rawQuote = safeSlice(block.text, at, at + 160);
  const previous = `${blocks[index - 1]?.text.slice(-80) || ""}\n\n${block.text.slice(Math.max(0, at - 80), at)}`;
  const following = `${block.text.slice(at + rawQuote.length, at + rawQuote.length + 80)}\n\n${blocks[index + 1]?.text.slice(0, 80) || ""}`;
  return { blockId: block.id, textOffset: at,
    textQuote: normalizeAnchorText(rawQuote) || undefined,
    quotePrefix: safeSlice(normalizeAnchorText(previous), -64) || undefined,
    quoteSuffix: safeSlice(normalizeAnchorText(following), 0, 64) || undefined };
}

/** Convert an index in collapsed whitespace back to a UTF-16 DOM text offset. */
function rawOffset(text: string, normalizedOffset: number) {
  let normalized = 0, seenText = false, whitespace = false;
  for (let index = 0; index < text.length; index += 1) {
    if (/\s/.test(text[index])) { if (seenText) whitespace = true; continue; }
    if (whitespace) { if (normalized === normalizedOffset) return Math.max(0, index - 1); normalized += 1; whitespace = false; }
    if (normalized === normalizedOffset) return index;
    normalized += 1; seenText = true;
  }
  return text.length;
}

/** Resolve exact text and context only. Equal plausible matches remain unresolved. */
export function resolveTextLocator(blocks: { id: string; text: string }[], locator: TextLocator, trustBlock = true): AnchorResolution {
  const identified = blocks.findIndex(block => block.id === locator.blockId);
  const exact = normalizeAnchorText(locator.textQuote || "");
  if (identified >= 0 && trustBlock) {
    const offset = Math.min(Math.max(locator.textOffset || 0, 0), blocks[identified].text.length);
    if (!exact || normalizeAnchorText(blocks[identified].text.slice(offset)).startsWith(exact)) return { blockIndex: identified, textOffset: offset, method: "block" };
  }
  if (!exact) return identified >= 0 ? { blockIndex: identified, textOffset: locator.textOffset || 0, method: "block" } : { reason: "missing" };
  const texts = blocks.map(block => normalizeAnchorText(block.text));
  const corpus = texts.join(" ");
  const prefix = normalizeAnchorText(locator.quotePrefix || ""), suffix = normalizeAnchorText(locator.quoteSuffix || "");
  const candidates: { start: number; score: number }[] = [];
  let at = corpus.indexOf(exact);
  while (at >= 0) {
    if (candidates.length >= 200) return { reason: "ambiguous" };
    const before = normalizeAnchorText(corpus.slice(Math.max(0, at - 100), at));
    const after = normalizeAnchorText(corpus.slice(at + exact.length, at + exact.length + 100));
    let left = 0, right = 0;
    while (left < prefix.length && left < before.length && prefix[prefix.length - left - 1] === before[before.length - left - 1]) left += 1;
    while (right < suffix.length && right < after.length && suffix[right] === after[right]) right += 1;
    candidates.push({ start: at, score: left + right });
    at = corpus.indexOf(exact, at + 1);
  }
  if (!candidates.length) return { reason: "missing" };
  candidates.sort((left, right) => right.score - left.score);
  if (candidates.length > 1 && (candidates[0].score < 8 || candidates[0].score - candidates[1].score < 4)) return { reason: "ambiguous" };
  let start = candidates[0].start;
  for (let index = 0; index < texts.length; index += 1) {
    if (start < texts[index].length) return { blockIndex: index, textOffset: rawOffset(blocks[index].text, start), method: "quote" };
    start -= texts[index].length + 1;
  }
  return { reason: "missing" };
}

const chapterBlocks = (container: HTMLElement) => Array.from(container.querySelectorAll<HTMLElement>("[data-block-id]"));
const textNodes = (element: HTMLElement) => {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  return nodes;
};
function characterRange(element: HTMLElement, offset: number) {
  const nodes = textNodes(element);
  let remaining = Math.max(0, offset);
  for (const node of nodes) {
    if (remaining < node.length) {
      const range = document.createRange();
      range.setStart(node, remaining); range.setEnd(node, Math.min(remaining + 1, node.length));
      return range;
    }
    remaining -= node.length;
  }
  return undefined;
}
function viewport(container: HTMLElement) {
  const bounds = container.getBoundingClientRect();
  const reader = container.closest(".reader");
  const header = reader?.querySelector(".reader__top")?.getBoundingClientRect();
  const footer = reader?.querySelector(".reader__bottom")?.getBoundingClientRect();
  return { top: header?.height ? Math.max(bounds.top, Math.min(bounds.bottom, header.bottom)) : bounds.top,
    bottom: footer?.height ? Math.min(bounds.bottom, Math.max(bounds.top, footer.top)) : bounds.bottom,
    left: bounds.left, right: bounds.right } as DOMRect;
}
function clips(element: HTMLElement, container: HTMLElement) {
  let bounds = viewport(container);
  let parent = element.parentElement;
  while (parent && parent !== container) {
    const style = getComputedStyle(parent);
    if ([style.overflow, style.overflowX, style.overflowY].some(value => ["hidden", "clip", "scroll", "auto"].includes(value))) {
      const box = parent.getBoundingClientRect();
      bounds = { ...bounds, top: Math.max(bounds.top, box.top), bottom: Math.min(bounds.bottom, box.bottom),
        left: Math.max(bounds.left, box.left), right: Math.min(bounds.right, box.right) } as DOMRect;
    }
    parent = parent.parentElement;
  }
  return bounds;
}
const intersects = (box: DOMRect, bounds: DOMRect) => box.width > 0 && box.height > 0 && box.bottom > bounds.top + 1
  && box.top < bounds.bottom && box.right > bounds.left + 1 && box.left < bounds.right;

/** Binary search text-node geometry, including the middle of long paragraphs. */
export const visibleBlockLocator = (container: HTMLElement, paged = false): TextLocator | undefined => {
  const elements = chapterBlocks(container);
  const values = elements.map(element => ({ id: element.dataset.blockId!, text: element.textContent || "" }));
  for (let index = 0; index < elements.length; index += 1) {
    const element = elements[index], bounds = clips(element, container);
    if (!Array.from(element.getClientRects()).some(box => intersects(box, bounds))) continue;
    let base = 0;
    for (const node of textNodes(element)) {
      let low = 0, high = node.length;
      while (low < high) {
        const mid = Math.floor((low + high) / 2), range = document.createRange();
        range.setStart(node, mid); range.setEnd(node, Math.min(mid + 1, node.length));
        const box = range.getBoundingClientRect();
        const before = paged ? box.right <= bounds.left + 1 : box.bottom <= bounds.top + 1;
        if (before) low = mid + 1; else high = mid;
      }
      for (let offset = low; offset < Math.min(node.length, low + 32); offset += 1) {
        const range = document.createRange(); range.setStart(node, offset); range.setEnd(node, offset + 1);
        if (Array.from(range.getClientRects()).some(box => intersects(box, bounds))) return quoteLocator(values, index, base + offset);
      }
      base += node.length;
    }
    if (!element.textContent?.trim()) return { blockId: element.dataset.blockId, textOffset: 0 };
  }
  return undefined;
};

export function selectedTextLocator(container: HTMLElement): TextLocator | undefined {
  const selection = window.getSelection();
  if (!selection?.rangeCount || selection.isCollapsed) return;
  const range = selection.getRangeAt(0);
  if (!container.contains(range.startContainer)) return;
  const start = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer as Element : range.startContainer.parentElement;
  const block = start?.closest<HTMLElement>("[data-block-id]");
  if (!block || !container.contains(block)) return;
  const before = document.createRange(); before.selectNodeContents(block); before.setEnd(range.startContainer, range.startOffset);
  const elements = chapterBlocks(container);
  return quoteLocator(elements.map(element => ({ id: element.dataset.blockId!, text: element.textContent || "" })), elements.indexOf(block), before.toString().length);
}

export function restoreTextLocator(container: HTMLElement, locator: TextLocator, options: { paged?: boolean; trustBlock?: boolean; blockOnly?: boolean } = {}) {
  const elements = chapterBlocks(container);
  const resolved = resolveTextLocator(elements.map(element => ({ id: element.dataset.blockId!, text: element.textContent || "" })),
    options.blockOnly ? { blockId: locator.blockId, textOffset: 0 } : locator, options.trustBlock ?? true);
  if ("reason" in resolved) return { matched: false as const, reason: resolved.reason };
  const element = elements[resolved.blockIndex];
  const range = characterRange(element, resolved.textOffset);
  const target = range?.getBoundingClientRect() || element.getBoundingClientRect();
  if (!target.width && !target.height) return { matched: false as const, reason: "missing" as const };
  const bounds = viewport(container);
  if (options.paged) {
    const width = container.clientWidth || 1;
    container.scrollLeft = Math.max(0, Math.min(container.scrollWidth - width, Math.floor((container.scrollLeft + target.left - bounds.left) / width) * width));
  } else container.scrollTop += target.top - bounds.top;
  const placed = range?.getBoundingClientRect() || element.getBoundingClientRect();
  if (!intersects(placed, clips(element, container))) return { matched: false as const, reason: "missing" as const };
  return { matched: true as const, locator: { ...locator, blockId: element.dataset.blockId, textOffset: resolved.textOffset }, method: resolved.method };
}

/** Compatible block-only entry point for chapter citations. */
export const restoreBlockLocator = (container: HTMLElement, blockId: string): boolean =>
  restoreTextLocator(container, { blockId }, { blockOnly: true }).matched;
