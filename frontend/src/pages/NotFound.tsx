import { Link } from "react-router-dom";
import { PageHeader } from "../components/ui";
import { usePageTitle } from "../hooks/usePageTitle";

export default function NotFound() {
  usePageTitle("Page not found");
  return (
    <div>
      <PageHeader title="Page not found" description="This address does not lead anywhere in Nexus." />
      <p><Link to="/">Go to Home</Link></p>
    </div>
  );
}
