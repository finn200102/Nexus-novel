import React from "react";
import { usePageTitle } from "../../hooks/usePageTitle";
import { PageHeader } from "../../components/ui";
import NotificationSettings from "../../components/notifications/NotificationSettings";
import FeedsAndWebhooks from "../../components/settings/FeedsAndWebhooks";
import "../../styles/integrations.css";
import { SETTINGS_BACK } from "./settingsNav";

const SettingsNotifications: React.FC = () => {
  usePageTitle("Notifications", { back: SETTINGS_BACK });
  return (
    <>
      <PageHeader title="Notifications" description="Get story updates on your phone, in your browser, or through other apps." />
      <NotificationSettings />
      <FeedsAndWebhooks />
    </>
  );
};

export default SettingsNotifications;
