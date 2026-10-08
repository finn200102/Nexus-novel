import type { CSSProperties } from "react";
import { FONTS, MEASURE_CH, ReaderTypography } from "./readerSettings";

/**
 * Inline style for reading text. Size is set in rem (user px / 16) so browser text zoom
 * still scales it; the measure is a custom property in ch of the reading font.
 */
export function typographyStyle(t: ReaderTypography): CSSProperties {
  return {
    fontFamily: FONTS.find((font) => font.value === t.font)?.family,
    fontSize: `${t.fontSize / 16}rem`,
    lineHeight: t.lineHeight,
    letterSpacing: t.letterSpacing ? `${t.letterSpacing}em` : undefined,
    wordSpacing: t.wordSpacing ? `${t.wordSpacing}em` : undefined,
    textAlign: t.justify ? "justify" : undefined,
    hyphens: t.hyphenate ? "auto" : "manual",
    ["--reader-measure" as string]: `${MEASURE_CH[t.width]}ch`,
  };
}
