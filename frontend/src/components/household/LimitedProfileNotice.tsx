import React from "react";
import { Badge, Banner } from "../ui";
import { useContentLimits } from "../../hooks/useContentLimits";
import { describeLimits } from "../../types/household";

/** A compact "Limited profile" badge with the limits as its tooltip; renders nothing when unlimited. */
export const LimitedProfileBadge: React.FC = () => {
  const limits = useContentLimits();
  if (!limits) return null;
  return (
    <Badge tone="info" title={describeLimits(limits)} data-testid="limited-profile-badge">
      Limited profile
    </Badge>
  );
};

/** Explains to a limited profile why some stories do not appear. Renders nothing when unlimited. */
export const LimitedProfileNotice: React.FC<{ className?: string }> = ({ className }) => {
  const limits = useContentLimits();
  if (!limits) return null;
  return (
    <Banner tone="info" className={className}>
      Limited profile: an administrator shows you {describeLimits(limits)}.
    </Banner>
  );
};
