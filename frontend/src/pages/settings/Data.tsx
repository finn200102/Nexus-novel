import React from "react";
import { usePageTitle } from "../../hooks/usePageTitle";
import { PageHeader } from "../../components/ui";
import ImportReadingReviews from "../../components/account/ImportReadingReviews";
import AccountDataPanel from "../../components/account/AccountDataPanel";
import HighlightsExport from "../../components/settings/HighlightsExport";
import CalibreExport from "../../components/settings/CalibreExport";
import { SETTINGS_BACK } from "./settingsNav";

const SettingsData: React.FC = () => {
  usePageTitle("Your data", { back: SETTINGS_BACK });
  return (
    <>
      <PageHeader title="Your data" description="Download a copy of your Nexus data, or restore one from an export file." />
      <AccountDataPanel />
      <ImportReadingReviews />
      <CalibreExport />
      <HighlightsExport />
    </>
  );
};

export default SettingsData;
