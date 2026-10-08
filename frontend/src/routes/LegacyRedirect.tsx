import { Navigate, useLocation, useParams, type Params } from "react-router-dom";
import { withSearch } from "./legacyRedirects";

/** Replaces the current entry with the new URL, keeping query string and hash. */
export function LegacyRedirect({ to }: { to: (params: Params) => string }) {
  const params = useParams();
  const { search, hash } = useLocation();
  return <Navigate replace to={withSearch(to(params), search, hash)} />;
}
