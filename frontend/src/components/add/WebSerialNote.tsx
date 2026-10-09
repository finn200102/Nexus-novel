import React from "react";
import { parseLinks } from "./addStoryEvents";
import { isKnownSiteUrl } from "./knownSites";

/** Shown under the link field when a pasted link is not from a known site. */
export const WebSerialNote: React.FC<{ links: string }> = ({ links }) => {
  const unknown = parseLinks(links).some((url) => /^https?:\/\//i.test(url) && !isKnownSiteUrl(url));
  if (!unknown) return null;
  return <p className="ui-field__hint" role="note">Nexus will try to read this as a web serial.</p>;
};
