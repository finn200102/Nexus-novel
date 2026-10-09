import React from "react";
import { usePageTitle } from "../../hooks/usePageTitle";
import { PageHeader, RadioCards } from "../../components/ui";
import { useTheme } from "../../theme/useTheme";
import type { ThemePreference } from "../../theme/themeStore";
import { SETTINGS_BACK } from "./settingsNav";

const SettingsAppearance: React.FC = () => {
  usePageTitle("Appearance", { back: SETTINGS_BACK });
  const { preference, setPreference } = useTheme();
  return (
    <>
      <PageHeader title="Appearance" description="Choose how Nexus looks on this device." />
      <section className="settings-group" aria-labelledby="settings-theme">
        <h2 id="settings-theme">Theme</h2>
        <RadioCards<ThemePreference>
          label="Theme"
          value={preference}
          onChange={setPreference}
          options={[
            { value: "system", label: "Match my device", description: "Light or dark, following your device setting." },
            { value: "light", label: "Light", description: "Bright pages with dark text." },
            { value: "dark", label: "Dark", description: "Dark pages with light text. Easier on the eyes at night." },
          ]}
        />
      </section>
    </>
  );
};

export default SettingsAppearance;
