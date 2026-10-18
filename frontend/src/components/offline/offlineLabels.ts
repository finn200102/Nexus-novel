export function offlineBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "Unknown";
  if (bytes < 1000) return `${Math.round(bytes)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1000, index = 0;
  while (size >= 1000 && index < units.length - 1) { size /= 1000; index++; }
  return `${size.toFixed(1)} ${units[index]}`;
}
