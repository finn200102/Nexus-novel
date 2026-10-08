import { Monitor, Moon, Sun } from "lucide-react";
import { SegmentedControl } from "../components/ui";
import { useTheme } from "./useTheme";
import type { ThemePreference } from "./themeStore";

/** System / Light / Dark switch. Used in Account until the D4 account menu takes it over. */
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
