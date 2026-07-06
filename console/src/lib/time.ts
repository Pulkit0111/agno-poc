export function relativeTime(epochSeconds: number): string {
  const s = Date.now() / 1000 - epochSeconds;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
