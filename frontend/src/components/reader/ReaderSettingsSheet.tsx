import { useId } from "react";
import { Minus, Plus, Type, X } from "lucide-react";
import { Button, IconButton, Popover, SegmentedControl, Sheet, Switch, cx, useRovingRadio } from "../ui";
import {
  AuthorNotesMode,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  FONTS,
  LETTER_SPACINGS,
  LINE_HEIGHTS,
  ReaderLayout,
  ReaderThemeChoice,
  ReaderThemeName,
  ReaderTypography,
  THEME_CHOICES,
  WORD_SPACINGS,
} from "./readerSettings";
import { typographyStyle } from "./typographyStyle";
import type { PreferenceSyncStatus } from "../../services/readerPreferenceSync";

export interface ReaderSettingsProps {
  typography: ReaderTypography;
  /** Theme actually shown (resolves "match app theme"). */
  resolvedTheme: ReaderThemeName;
  /** Reader theme that "Match app" currently stands for. */
  appTheme: ReaderThemeName;
  onChange: <K extends keyof ReaderTypography>(key: K, value: ReaderTypography[K]) => void;
  layout: ReaderLayout;
  onLayout: (layout: ReaderLayout) => void;
  authorNotes: AuthorNotesMode;
  onAuthorNotes: (mode: AuthorNotesMode) => void;
  storyOnly: boolean;
  onStoryOnly: (value: boolean) => void;
  onUseForAll: () => void;
  sync?: PreferenceSyncStatus;
  onResolveSync?: (choice: "account" | "device") => Promise<void>;
}

const THEME_LABELS: Record<ReaderThemeChoice, string> = { app: "Match app", paper: "Paper", sepia: "Sepia", night: "Night", black: "Black" };

function ThemePicker({ value, onChange, appTheme }: { value: ReaderThemeChoice; onChange: (v: ReaderThemeChoice) => void; appTheme: ReaderThemeName }) {
  const { register, tabStop, onKeyDown } = useRovingRadio(THEME_CHOICES, value, onChange);
  return (
    <div role="radiogroup" aria-label="Theme" className="reader-settings__swatches" onKeyDown={onKeyDown}>
      {THEME_CHOICES.map((choice) => (
        <button
          key={choice}
          ref={register(choice)}
          type="button"
          role="radio"
          aria-checked={choice === value}
          tabIndex={choice === tabStop ? 0 : -1}
          className="reader-settings__swatch"
          onClick={() => onChange(choice)}
        >
          <span className="reader-settings__swatch-chip" data-reader-theme={choice === "app" ? appTheme : choice} aria-hidden="true">Aa</span>
          {THEME_LABELS[choice]}
        </button>
      ))}
    </div>
  );
}

function FontPicker({ value, onChange }: { value: ReaderTypography["font"]; onChange: (v: ReaderTypography["font"]) => void }) {
  const values = FONTS.map((font) => font.value);
  const { register, tabStop, onKeyDown } = useRovingRadio(values, value, onChange);
  return (
    <div role="radiogroup" aria-label="Font" className="reader-settings__fonts" onKeyDown={onKeyDown}>
      {FONTS.map((font) => (
        <button
          key={font.value}
          ref={register(font.value)}
          type="button"
          role="radio"
          aria-checked={font.value === value}
          tabIndex={font.value === tabStop ? 0 : -1}
          className="reader-settings__font"
          style={{ fontFamily: font.family }}
          onClick={() => onChange(font.value)}
        >
          {font.label}
        </button>
      ))}
    </div>
  );
}

const spacingLabel = (value: number, i: number) => (i === 0 ? "Normal" : i === 1 ? "Wide" : "Wider") + (value ? ` (${value}em)` : "");

/** The text settings panel body (shared by the desktop popover and the phone sheet). */
export function ReaderSettingsPanel(props: ReaderSettingsProps) {
  const { typography: t, onChange, resolvedTheme } = props;
  const sizeId = useId();
  return (
    <div className="reader-settings">
      {props.sync && <div className="reader-settings__group" role="status">
        {props.sync.conflicts.length ? <><p>Settings changed on another device. Your changes are still saved here.</p><Button size="sm" onClick={() => void props.onResolveSync?.("account")}>Use account settings</Button><Button size="sm" variant="secondary" onClick={() => void props.onResolveSync?.("device")}>Keep this device’s settings</Button></>
          : props.sync.memoryOnly ? <p>Browser storage is unavailable. Settings remain in memory while this page is open.</p>
          : props.sync.error ? <p>{props.sync.error}</p>
          : props.sync.pending || props.sync.offline ? <p>Settings saved here; waiting to synchronize.</p>
          : <p>Settings follow your account across devices.</p>}
      </div>}
      <p className="reader-settings__preview" data-reader-theme={resolvedTheme} style={typographyStyle({ ...t, fontSize: Math.min(t.fontSize, 22) })}>
        The ledger was bound in grey calfskin and smelled faintly of lamp oil.
      </p>

      <div className="reader-settings__group">
        <span className="reader-settings__label" aria-hidden="true">Theme</span>
        <ThemePicker value={t.theme} onChange={(v) => onChange("theme", v)} appTheme={props.appTheme} />
      </div>

      <div className="reader-settings__group">
        <span className="reader-settings__label" aria-hidden="true">Font</span>
        <FontPicker value={t.font} onChange={(v) => onChange("font", v)} />
      </div>

      <div className="reader-settings__group">
        <span className="reader-settings__label" id={sizeId}>Size</span>
        <div className="reader-settings__stepper" role="group" aria-labelledby={sizeId}>
          <IconButton label="Smaller text" icon={<Minus />} outlined tooltip="none" disabled={t.fontSize <= FONT_SIZE_MIN} onClick={() => onChange("fontSize", Math.max(FONT_SIZE_MIN, t.fontSize - 1))} />
          <output aria-live="polite" aria-label="Text size">{t.fontSize}</output>
          <IconButton label="Larger text" icon={<Plus />} outlined tooltip="none" disabled={t.fontSize >= FONT_SIZE_MAX} onClick={() => onChange("fontSize", Math.min(FONT_SIZE_MAX, t.fontSize + 1))} />
        </div>
      </div>

      <div className="reader-settings__group">
        <span className="reader-settings__label" aria-hidden="true">Line spacing</span>
        <SegmentedControl
          label="Line spacing"
          block
          options={LINE_HEIGHTS.map((stop) => ({ value: String(stop.value), label: stop.label }))}
          value={String(t.lineHeight)}
          onChange={(v) => onChange("lineHeight", Number(v))}
        />
      </div>

      <div className="reader-settings__group">
        <span className="reader-settings__label" aria-hidden="true">Width</span>
        <SegmentedControl
          label="Text width"
          block
          options={[{ value: "narrow", label: "Narrow" }, { value: "medium", label: "Medium" }, { value: "wide", label: "Wide" }]}
          value={t.width}
          onChange={(v) => onChange("width", v)}
        />
      </div>

      <details className="reader-settings__more">
        <summary>Spacing and justification</summary>
        <div className="reader-settings__more-body">
          <div className="reader-settings__group">
            <span className="reader-settings__label" aria-hidden="true">Letter spacing</span>
            <SegmentedControl
              label="Letter spacing"
              block
              options={LETTER_SPACINGS.map((v, i) => ({ value: String(v), label: i === 0 ? "Normal" : i === 1 ? "Wide" : "Wider", ariaLabel: spacingLabel(v, i) }))}
              value={String(t.letterSpacing)}
              onChange={(v) => onChange("letterSpacing", Number(v))}
            />
          </div>
          <div className="reader-settings__group">
            <span className="reader-settings__label" aria-hidden="true">Word spacing</span>
            <SegmentedControl
              label="Word spacing"
              block
              options={WORD_SPACINGS.map((v, i) => ({ value: String(v), label: i === 0 ? "Normal" : i === 1 ? "Wide" : "Wider", ariaLabel: spacingLabel(v, i) }))}
              value={String(t.wordSpacing)}
              onChange={(v) => onChange("wordSpacing", Number(v))}
            />
          </div>
          <div className="reader-settings__group">
            <span className="reader-settings__label" aria-hidden="true">Paragraphs</span>
            <SegmentedControl
              label="Paragraph style"
              block
              options={[{ value: "spaced", label: "Spaced" }, { value: "indented", label: "Indented" }]}
              value={t.paragraphStyle}
              onChange={(v) => onChange("paragraphStyle", v)}
            />
          </div>
          <Switch label="Justify text" checked={t.justify} onChange={(v) => onChange("justify", v)} />
          <Switch label="Hyphenation" checked={t.hyphenate} onChange={(v) => onChange("hyphenate", v)} />
        </div>
      </details>

      <div className="reader-settings__group">
        <span className="reader-settings__label" aria-hidden="true">Reading mode</span>
        <SegmentedControl
          label="Reading mode"
          block
          options={[{ value: "scroll", label: "Scroll" }, { value: "paged", label: "Pages" }]}
          value={props.layout}
          onChange={props.onLayout}
        />
      </div>

      <div className="reader-settings__group">
        <span className="reader-settings__label" aria-hidden="true">Author’s notes</span>
        <SegmentedControl
          label="Author’s notes"
          block
          options={[{ value: "shown", label: "Show" }, { value: "collapsed", label: "Collapse" }, { value: "hidden", label: "Hide" }]}
          value={props.authorNotes}
          onChange={props.onAuthorNotes}
        />
      </div>

      <div className="reader-settings__scope">
        <Switch label="Only for this story" checked={props.storyOnly} onChange={props.onStoryOnly} />
        <p className="text-xs text-muted">
          {props.storyOnly ? "Changes apply to this story only." : "Changes apply to every story."}
        </p>
        {props.storyOnly && <Button variant="ghost" size="sm" onClick={props.onUseForAll}>Use these settings for all stories</Button>}
      </div>
    </div>
  );
}

interface ReaderSettingsControlProps extends ReaderSettingsProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Phones: bottom sheet; otherwise a popover anchored to the Aa button. */
  compact: boolean;
}

/** "Aa" button plus its panel: popover on desktop, bottom sheet on phones. */
export default function ReaderSettingsControl({ open, onOpenChange, compact, ...props }: ReaderSettingsControlProps) {
  if (compact) {
    return (
      <>
        <IconButton label="Text settings" icon={<Type />} tooltip="below" aria-expanded={open} aria-haspopup="dialog" onClick={() => onOpenChange(!open)} />
        <Sheet open={open} onClose={() => onOpenChange(false)} title="Text settings" variant="bottom" className="reader-settings-sheet" closeLabel="Close text settings">
          <ReaderSettingsPanel {...props} />
        </Sheet>
      </>
    );
  }
  return (
    <Popover
      label="Text settings"
      align="end"
      open={open}
      onOpenChange={onOpenChange}
      className={cx("reader-settings-anchor")}
      trigger={(p) => <IconButton {...p} label="Text settings" icon={<Type />} tooltip="below" aria-haspopup="dialog" />}
    >
      {(close) => (
        <>
          <div className="reader-settings__head">
            <h2 className="reader-settings__title">Text settings</h2>
            <IconButton label="Close text settings" icon={<X />} tooltip="none" size="sm" onClick={close} />
          </div>
          <ReaderSettingsPanel {...props} />
        </>
      )}
    </Popover>
  );
}
