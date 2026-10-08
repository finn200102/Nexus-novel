import apiClient from "./apiClient";

export type SourceState = "ok" | "degraded" | "rate_limited" | "down";

export interface SourceStatus {
  site: string;
  label: string;
  state: SourceState;
  /** ISO time the rate-limit cooldown ends, when known. */
  until: string | null;
  message: string;
}

export const sourceStatusService = {
  async list(): Promise<SourceStatus[]> {
    const response = await apiClient.get<{ sites: SourceStatus[] }>("/sources/status");
    return response.data.sites;
  },
};

/** Local wall-clock time such as "14:20". */
export const formatResumeTime = (iso: string): string =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

export const describeSourceStatus = (status: SourceStatus): string => {
  if (status.state === "rate_limited" && status.until) {
    return `${status.message.replace(/\.$/, "")} — updates resume around ${formatResumeTime(status.until)}`;
  }
  return status.message;
};

export const sourceChipLabel = (status: SourceStatus): string => {
  switch (status.state) {
    case "rate_limited":
      return status.until ? `Rate-limited until ${formatResumeTime(status.until)}` : "Rate-limited";
    case "down":
      return "Source down";
    case "degraded":
      return "Source slow";
    default:
      return "Source OK";
  }
};
