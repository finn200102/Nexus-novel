import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useDismiss } from "./useDismiss";
import { cx } from "./cx";

export type MenuItem =
  | {
      type?: "item";
      label: string;
      icon?: ReactNode;
      onSelect: () => void;
      danger?: boolean;
      disabled?: boolean;
      /** Short hint on the right, e.g. a shortcut. */
      hint?: string;
    }
  | { type: "separator" };

/** Props to spread on the trigger button. */
export interface MenuTriggerProps {
  ref: (node: HTMLButtonElement | null) => void;
  id: string;
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  "aria-controls": string;
  onClick: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}

export interface MenuProps {
  /** Render the trigger (Button or IconButton) with the given props spread on it. */
  trigger: (props: MenuTriggerProps) => ReactNode;
  items: MenuItem[];
  /** Horizontal alignment of the menu with the trigger. Default "start". */
  align?: "start" | "end";
  className?: string;
}

type Item = Extract<MenuItem, { onSelect: () => void }>;
const isItem = (item: MenuItem): item is Item => item.type !== "separator";

/**
 * Action menu (APG menu button): Enter/Space/ArrowDown open on the first item, ArrowUp on the
 * last; arrows wrap, Home/End, typeahead; Escape closes and returns focus; Tab closes.
 */
export function Menu({ trigger, items, align = "start", className }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const id = useId();
  const menuId = `${id}-menu`;
  const triggerId = `${id}-trigger`;
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const typeahead = useRef({ text: "", time: 0 });

  const actionable = useMemo(
    () => items.map((item, index) => ({ item, index })).filter((x): x is { item: Item; index: number } => isItem(x.item) && !x.item.disabled),
    [items],
  );

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  const refs = useMemo(() => [menuRef, triggerRef], []);
  const onDismiss = useCallback((reason: "outside" | "escape") => close(reason === "escape"), [close]);
  useDismiss(refs, open, onDismiss);

  const openAt = (which: "first" | "last") => {
    if (!actionable.length) return;
    setActive(which === "first" ? 0 : actionable.length - 1);
    setOpen(true);
  };

  useEffect(() => {
    if (open) itemRefs.current[actionable[active]?.index]?.focus();
  }, [open, active, actionable]);

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openAt("first");
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      openAt("last");
    }
  };

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const n = actionable.length;
    if (!n) return;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActive((a) => (a + 1) % n);
        return;
      case "ArrowUp":
        event.preventDefault();
        setActive((a) => (a - 1 + n) % n);
        return;
      case "Home":
        event.preventDefault();
        setActive(0);
        return;
      case "End":
        event.preventDefault();
        setActive(n - 1);
        return;
      case "Tab":
        close(false);
        return;
      default:
        if (event.key.length === 1 && /\S/.test(event.key)) {
          const now = Date.now();
          const t = typeahead.current;
          t.text = now - t.time > 500 ? event.key.toLowerCase() : t.text + event.key.toLowerCase();
          t.time = now;
          // Repeating one letter cycles through items starting with it.
          const repeated = t.text.split("").every((c) => c === t.text[0]);
          const query = repeated ? t.text[0] : t.text;
          const start = query.length === 1 ? active + 1 : active;
          for (let k = 0; k < n; k++) {
            const candidate = (start + k) % n;
            if (actionable[candidate].item.label.toLowerCase().startsWith(query)) {
              setActive(candidate);
              break;
            }
          }
        }
    }
  };

  return (
    <div className={cx("ui-menu-anchor", className)}>
      {trigger({
        ref: (node) => {
          triggerRef.current = node;
        },
        id: triggerId,
        "aria-haspopup": "menu",
        "aria-expanded": open,
        "aria-controls": menuId,
        onClick: () => (open ? close() : openAt("first")),
        onKeyDown: onTriggerKeyDown,
      })}
      <div
        ref={menuRef}
        id={menuId}
        role="menu"
        aria-labelledby={triggerId}
        className={cx("ui-menu", `ui-menu--${align}`)}
        hidden={!open}
        onKeyDown={onMenuKeyDown}
      >
        {items.map((item, index) =>
          isItem(item) ? (
            <button
              key={index}
              ref={(node) => {
                itemRefs.current[index] = node;
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              disabled={item.disabled}
              aria-disabled={item.disabled || undefined}
              className={cx("ui-menu__item", item.danger && "ui-menu__item--danger")}
              onClick={() => {
                close();
                item.onSelect();
              }}
            >
              {item.icon}
              <span className="ui-menu__label">{item.label}</span>
              {item.hint && <span className="ui-menu__hint">{item.hint}</span>}
            </button>
          ) : (
            <div key={index} role="separator" className="ui-menu__separator" />
          ),
        )}
      </div>
    </div>
  );
}
