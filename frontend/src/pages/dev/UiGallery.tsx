import { useState, type ReactNode } from "react";
import { Bell, Download, Grid2x2, List, Plus, Settings, Trash2 } from "lucide-react";
import {
  Badge,
  Button,
  Checkbox,
  CountBadge,
  Field,
  FilterChip,
  IconButton,
  Input,
  InputChip,
  RadioCards,
  SegmentedControl,
  Select,
  Switch,
  TextArea,
} from "../../components/ui";
import { ThemeSwitcher } from "../../theme/ThemeSwitcher";
import { GalleryOverlays } from "./GalleryOverlays";
import "./ui-gallery.css";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="gallery__section" aria-labelledby={`g-${title}`}>
      <h2 id={`g-${title}`} className="text-xl">
        {title}
      </h2>
      <div className="gallery__row">{children}</div>
    </section>
  );
}

/** Dev-only gallery of every UI primitive (/dev/ui). Used for visual review and axe checks. */
export default function UiGallery() {
  const [search, setSearch] = useState("dragon");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [mode, setMode] = useState<"scroll" | "pages">("scroll");
  const [format, setFormat] = useState<"epub" | "pdf" | "txt">("epub");
  const [notify, setNotify] = useState(true);
  const [completed, setCompleted] = useState(false);
  const [tags, setTags] = useState(["Fantasy", "Slow burn", "LitRPG"]);
  const [genres, setGenres] = useState<string[]>(["Fantasy"]);

  return (
    <main id="main" className="gallery">
      <header className="gallery__header">
        <h1 className="text-2xl">UI primitives</h1>
        <ThemeSwitcher />
      </header>

      <Section title="Buttons">
        <Button variant="primary" icon={<Plus aria-hidden="true" />}>Add story</Button>
        <Button>Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger" icon={<Trash2 aria-hidden="true" />}>Delete shelf</Button>
        <Button variant="primary" loading>Saving</Button>
        <Button disabled>Disabled</Button>
        <Button size="sm">Small</Button>
        <Button size="lg" variant="primary">Large</Button>
      </Section>

      <Section title="Icon buttons">
        <IconButton label="Notifications" icon={<Bell />} />
        <IconButton label="Settings" icon={<Settings />} outlined />
        <IconButton label="Download" icon={<Download />} size="sm" />
        <IconButton label="Grid view" icon={<Grid2x2 />} pressed={layout === "grid"} onClick={() => setLayout("grid")} />
        <IconButton label="List view" icon={<List />} pressed={layout === "list"} onClick={() => setLayout("list")} />
      </Section>

      <Section title="Fields">
        <div className="gallery__grid">
          <Input label="Display name" hint="Shown on your shelves." defaultValue="Finn" />
          <Input label="Email" type="email" required error="Enter an email address like name@example.com." defaultValue="finn@" />
          <Input
            label="Search"
            hideLabel
            search
            placeholder="Search stories"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onClear={() => setSearch("")}
          />
          <Select
            label="Sort by"
            options={[
              { value: "updated", label: "Recently updated" },
              { value: "title", label: "Title" },
              { value: "added", label: "Date added" },
            ]}
          />
          <TextArea label="Note" hint="Only you can see notes." />
          <Field label="Custom control" hint="Field wires id, hint and error for any control.">
            {(props) => <input className="ui-input" type="number" defaultValue={3} {...props} />}
          </Field>
        </div>
      </Section>

      <Section title="Choices">
        <Checkbox label="Mark as completed" hint="Hides it from Continue reading." checked={completed} onChange={(e) => setCompleted(e.target.checked)} />
        <Switch label="New chapter notifications" checked={notify} onChange={setNotify} />
        <SegmentedControl
          label="Layout"
          value={layout}
          onChange={setLayout}
          options={[
            { value: "grid", label: "Grid", icon: <Grid2x2 aria-hidden="true" /> },
            { value: "list", label: "List", icon: <List aria-hidden="true" /> },
          ]}
        />
        <SegmentedControl
          label="Reading mode"
          value={mode}
          onChange={setMode}
          options={[
            { value: "scroll", label: "Scroll" },
            { value: "pages", label: "Pages" },
          ]}
        />
        <div className="gallery__stack">
        <RadioCards
          label="Download format"
          value={format}
          onChange={setFormat}
          options={[
            { value: "epub", label: "EPUB", description: "Best for e-readers." },
            { value: "pdf", label: "PDF", description: "Fixed layout for printing." },
            { value: "txt", label: "Plain text", description: "No formatting.", disabled: true },
          ]}
        />
        </div>
      </Section>

      <Section title="Chips and badges">
        {["Fantasy", "Sci-fi", "Romance"].map((genre) => (
          <FilterChip
            key={genre}
            selected={genres.includes(genre)}
            onChange={(on) => setGenres(on ? [...genres, genre] : genres.filter((g) => g !== genre))}
          >
            {genre}
          </FilterChip>
        ))}
        {tags.map((tag) => (
          <InputChip key={tag} removeLabel={`Remove tag ${tag}`} onRemove={() => setTags(tags.filter((t) => t !== tag))}>
            {tag}
          </InputChip>
        ))}
        <Badge>Neutral</Badge>
        <Badge tone="accent">Reading</Badge>
        <Badge tone="info">New</Badge>
        <Badge tone="success">Complete</Badge>
        <Badge tone="warning">Paused</Badge>
        <Badge tone="danger">Failed</Badge>
        <CountBadge count={3} label="3 stories with new chapters" />
      </Section>

      <GalleryOverlays />
    </main>
  );
}
