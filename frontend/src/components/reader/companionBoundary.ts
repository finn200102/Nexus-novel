/** Source labels are signed identifiers. A blank boundary delegates only to verified server evidence. */
export function companionBoundary(raw: string, currentChapter: number): number | undefined | null {
  if (!raw.trim()) return undefined;
  const value = Number(raw);
  return Number.isInteger(value) && value >= -2147483648 && value <= 2147483647 && value <= currentChapter ? value : null;
}
export const initialCompanionBoundary = (chapter: number) => chapter > -2147483648 ? String(chapter - 1) : "";
