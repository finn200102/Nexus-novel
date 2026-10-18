/** The same bounded raster data-URI family accepted by chapter sanitization.
 * External URLs and temporary object URLs are not a durable offline asset.
 */
export function offlineImageSource(tag: string): string | null {
  const source = tag.match(/(?:^|[\t\n\r\f ])src\s*=\s*["']([^"']*)["']/i)?.[1];
  if (!source || source.length > 3_000_000) return null;
  return /^data:image\/(?:png|jpeg|webp|gif);base64,(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/i.test(source)
    && !source.endsWith(',') ? source : null;
}
