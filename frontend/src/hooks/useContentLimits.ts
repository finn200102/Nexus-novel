import { useEffect, useState } from "react";
import { householdService } from "../services/householdService";
import type { ContentLimits } from "../types/household";

let shared: Promise<ContentLimits | null> | null = null;

/** Forget the cached limits, e.g. between tests or after an admin changes them. */
export const resetContentLimitsCache = () => {
  shared = null;
};

/**
 * The signed-in profile's content limits (set by an administrator), or null when the profile has
 * none or they could not be loaded. One request is shared by every consumer.
 */
export const useContentLimits = (): ContentLimits | null => {
  const [limits, setLimits] = useState<ContentLimits | null>(null);
  useEffect(() => {
    if (!shared) {
      shared = householdService.myLimits().catch(() => {
        shared = null;
        return null;
      });
    }
    let active = true;
    void shared.then((value) => active && setLimits(value));
    return () => {
      active = false;
    };
  }, []);
  return limits?.limited ? limits : null;
};
