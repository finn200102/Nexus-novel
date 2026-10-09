import React from "react";
import { usePageTitle } from "../../hooks/usePageTitle";
import { PageHeader } from "../../components/ui";
import HiddenContentPanel from "../../components/organization/HiddenContentPanel";
import "../../styles/organization.css";
import { SETTINGS_BACK } from "./settingsNav";

const SettingsHidden: React.FC = () => {
  usePageTitle("Hidden content", { back: SETTINGS_BACK });
  return (
    <>
      <PageHeader title="Hidden content" description="Tags, fandoms, genres, authors and words you never want to see in discovery." />
      <HiddenContentPanel />
    </>
  );
};

export default SettingsHidden;
