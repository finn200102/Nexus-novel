import { Monitor, Moon, Sun } from "lucide-react";
import { SegmentedControl } from "../components/ui";
import { useTheme } from "./useTheme";
import type { ThemePreference } from "./themeStore";

/** System / Light / Dark switch: sidebar profile menu and the phone More page (Settings › Appearance in D12). */
export function ThemeSwitcher({ className }: { className?: string }) {
  const { preference, setPreference } = useTheme();
  return (
    <SegmentedControl<ThemePreference>
      label="Theme"
      className={className}
      value={preference}
      onChange={setPreference}
      options={[
        { value: "system", label: "System", icon: <Monitor aria-hidden="true" /> },
        { value: "light", label: "Light", icon: <Sun aria-hidden="true" /> },
        { value: "dark", label: "Dark", icon: <Moon aria-hidden="true" /> },
      ]}
    />
  );
}
