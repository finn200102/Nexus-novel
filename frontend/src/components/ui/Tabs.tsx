import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./cx";

export interface TabItem<T extends string> {
  value: T;
  label: ReactNode;
  /** Panel content; omit when the tabs drive routes and the page renders the content. */
  panel?: ReactNode;
  disabled?: boolean;
}

export interface TabsProps<T extends string> {
  /** Accessible name of the tab list. */
  label: string;
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Stick below the top bar while scrolling. */
  sticky?: boolean;
  className?: string;
}

/** APG tabs with automatic activation: arrows move and select, Home/End jump. */
export function Tabs<T extends string>({ label, items, value, onChange, sticky, className }: TabsProps<T>) {
  const base = useId();
  const refs = useRef(new Map<T, HTMLButtonElement>());
  const enabled = items.filter((item) => !item.disabled);
  const hasPanels = items.some((item) => item.panel !== undefined);

  const onKeyDown = (event: KeyboardEvent) => {
    const index = enabled.findIndex((item) => item.value === value);
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % enabled.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + enabled.length) % enabled.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = enabled.length - 1;
    if (next === null) return;
    event.preventDefault();
    const target = enabled[next].value;
    onChange(target);
    refs.current.get(target)?.focus();
  };

  return (
    <div className={cx("ui-tabs", className)}>
      <div className={cx("ui-tabs__scroller", sticky && "ui-tabs__scroller--sticky")}>
        <div role="tablist" aria-label={label} className="ui-tabs__list" onKeyDown={onKeyDown}>
          {items.map((item) => {
            const selected = item.value === value;
            return (
              <button
                key={item.value}
                ref={(node) => {
                  if (node) refs.current.set(item.value, node);
                  else refs.current.delete(item.value);
                }}
                id={`${base}-tab-${item.value}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={item.panel !== undefined ? `${base}-panel-${item.value}` : undefined}
                tabIndex={selected ? 0 : -1}
                disabled={item.disabled}
                className="ui-tabs__tab"
                onClick={() => onChange(item.value)}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </div>
      {hasPanels &&
        items.map((item) =>
          item.panel === undefined ? null : (
            <div
              key={item.value}
              id={`${base}-panel-${item.value}`}
              role="tabpanel"
              aria-labelledby={`${base}-tab-${item.value}`}
              hidden={item.value !== value}
              tabIndex={0}
              className="ui-tabs__panel"
            >
              {item.value === value && item.panel}
            </div>
          ),
        )}
    </div>
  );
}
