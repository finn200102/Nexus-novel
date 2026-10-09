import React from "react";
import { usePageTitle } from "../../hooks/usePageTitle";
import { PageHeader } from "../../components/ui";
import EReaderSettings from "../../components/ereader/EReaderSettings";
import KoboSettings from "../../components/ereader/KoboSettings";
import { SETTINGS_BACK } from "./settingsNav";

const SettingsEReaders: React.FC = () => {
  usePageTitle("E-readers", { back: SETTINGS_BACK });
  return (
    <>
      <PageHeader title="E-readers" description="Send stories to your e-reader from Nexus." />
      <EReaderSettings />
      <KoboSettings />
    </>
  );
};

export default SettingsEReaders;
