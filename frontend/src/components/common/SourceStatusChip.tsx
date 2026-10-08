import React from "react";
import { useAuth } from "../../context/AuthContext";
import { useSourceStatus } from "../../hooks/useSourceStatus";
import { describeSourceStatus, sourceChipLabel } from "../../services/sourceStatusService";
import "../../styles/source-status.css";

interface SourceStatusChipProps {
  site: string | null | undefined;
}

/** Health of one novel's source site, for the novel detail page. */
const SourceStatusChip: React.FC<SourceStatusChipProps> = ({ site }) => {
  const { isAuthenticated } = useAuth();
  const sites = useSourceStatus(isAuthenticated);
  const status = site ? sites.find((item) => item.site === site) : undefined;
  if (!status) return null;

  return (
    <span className={`source-status-chip source-status-chip--${status.state}`} title={describeSourceStatus(status)}>
      {sourceChipLabel(status)}
    </span>
  );
};

export default SourceStatusChip;
