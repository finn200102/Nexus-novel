import React from "react";
import NotificationSettings from "../components/notifications/NotificationSettings";
import "../styles/integrations.css";

const NotificationSettingsPage: React.FC = () => (
  <div className="integrations-page">
    <header className="integrations-page__header">
      <div>
        <p className="library-workspace__eyebrow">Your account</p>
        <h1>Notifications</h1>
        <p>Get story updates on your phone, in your browser, or through other apps.</p>
      </div>
    </header>
    <NotificationSettings />
  </div>
);

export default NotificationSettingsPage;
