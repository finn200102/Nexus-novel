import { useEffect, useState } from "react";
import apiClient from "../../services/apiClient";
import { Badge } from "../ui";

export type HiatusState = "active" | "slowing" | "hiatus";

export interface HiatusInfo {
  state: HiatusState;
  last_update_at: string | null;
  label: string;
}

/** Small status pill for a story's update rhythm. Muted when active, warning on hiatus. */
export default function HiatusBadge({ metadataId }: { metadataId: number }) {
  const [hiatus, setHiatus] = useState<HiatusInfo | null>(null);

  useEffect(() => {
    let active = true;
    apiClient
      .get<{ hiatus?: HiatusInfo }>(`/stories/${metadataId}`)
      .then((response) => {
        if (active) setHiatus(response.data?.hiatus ?? null);
      })
      .catch(() => {
        if (active) setHiatus(null);
      });
    return () => {
      active = false;
    };
  }, [metadataId]);

  if (!hiatus) return null;
  const tone = hiatus.state === "hiatus" ? "warning" : hiatus.state === "slowing" ? "info" : "neutral";
  return <Badge tone={tone} className={`hiatus-badge hiatus-badge--${hiatus.state}`}>{hiatus.label}</Badge>;
}
