import { Bell, Compass, Home, Library, type LucideIcon } from "lucide-react";

export interface MainNavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  /** Path prefixes that also mark this item as current. */
  match: string[];
  /** The Updates item carries the unread badge. */
  badge?: boolean;
}

/** The four reader destinations, in the same order in the sidebar and the tab bar. */
export const MAIN_NAV: MainNavItem[] = [
  { label: "Home", to: "/", icon: Home, match: [] },
  { label: "Discover", to: "/discover", icon: Compass, match: ["/discover", "/story"] },
  { label: "Library", to: "/library", icon: Library, match: ["/library"] },
  { label: "Updates", to: "/updates", icon: Bell, match: ["/updates"], badge: true },
];

export const isCurrent = (pathname: string, to: string, match: string[]) =>
  to === "/" ? pathname === "/" : match.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));

export const unreadLabel = (count: number) =>
  `${count} ${count === 1 ? "story" : "stories"} with new chapters`;

/** Initials for the avatar: "Mira V." → "MV", "reader" → "R". */
export const initials = (name: string) =>
  name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("") || "R";
