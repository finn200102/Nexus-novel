// Heuristic detection of author's notes at the start/end of a chapter.
// Chapter text is plain text split on "\n"; a note run is consecutive
// non-blank paragraphs that each begin with a note marker.

export interface AuthorNoteSplit {
  head: string[];
  body: string[];
  tail: string[];
}

const NOTE_MARKER = /^\s*(a\/n\b|an:|author['’]?s\s+note|note:)/i;

export const isAuthorNoteParagraph = (paragraph: string): boolean => NOTE_MARKER.test(paragraph);

const isBlank = (paragraph: string) => paragraph.trim() === "";

const isNote = (paragraph: string) => !isBlank(paragraph) && isAuthorNoteParagraph(paragraph);

export function splitAuthorNotes(paragraphs: string[]): AuthorNoteSplit {
  const total = paragraphs.length;

  let start = 0;
  while (start < total && isBlank(paragraphs[start])) start++;

  let headEnd = start;
  while (headEnd < total && isNote(paragraphs[headEnd])) headEnd++;

  let end = total;
  while (end > headEnd && isBlank(paragraphs[end - 1])) end--;

  let tailStart = end;
  while (tailStart > headEnd && isNote(paragraphs[tailStart - 1])) tailStart--;

  // Blank separators between the body and a trailing note belong to neither.
  let bodyEnd = tailStart;
  if (tailStart < end) {
    while (bodyEnd > headEnd && isBlank(paragraphs[bodyEnd - 1])) bodyEnd--;
  }

  // Blank separators after a leading note are dropped as well.
  let bodyStart = headEnd;
  while (bodyStart < bodyEnd && isBlank(paragraphs[bodyStart])) bodyStart++;

  return {
    head: paragraphs.slice(start, headEnd),
    body: paragraphs.slice(bodyStart, bodyEnd),
    tail: paragraphs.slice(tailStart, end),
  };
}
