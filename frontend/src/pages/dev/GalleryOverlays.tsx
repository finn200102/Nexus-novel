import { useState, type ReactNode } from "react";
import { BookOpen, Copy, Filter, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import {
  Badge,
  Banner,
  Button,
  Card,
  Cover,
  Dialog,
  EmptyState,
  IconButton,
  Input,
  ListRow,
  Menu,
  PageHeader,
  Popover,
  Progress,
  Sheet,
  Skeleton,
  SkeletonGroup,
  Switch,
  Tabs,
} from "../../components/ui";
import { useToast } from "../../context/useToast";

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

const TITLES = ["The Wandering Inn", "Mother of Learning", "Worm", "A Practical Guide to Evil", "Super Supportive", "Beware of Chicken"];

/** D3 primitives for the dev gallery. */
export function GalleryOverlays() {
  const [dialog, setDialog] = useState(false);
  const [sheet, setSheet] = useState<null | "auto" | "bottom" | "side">(null);
  const [tab, setTab] = useState<"overview" | "chapters" | "notes">("overview");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { addToast } = useToast();

  return (
    <>
      <Section title="Page header">
        <div className="gallery__stack">
          <PageHeader
            title="Library"
            description="Everything you follow, in one place."
            actions={<Button variant="primary">Add story</Button>}
          />
        </div>
      </Section>

      <Section title="Menu and popover">
        <Menu
          trigger={(props) => <IconButton {...props} label="More actions" icon={<MoreHorizontal />} outlined />}
          items={[
            { label: "Rename", icon: <Pencil aria-hidden="true" />, onSelect: () => addToast("Renamed", "success") },
            { label: "Duplicate", icon: <Copy aria-hidden="true" />, onSelect: () => addToast("Duplicated", "info") },
            { label: "Disabled item", disabled: true, onSelect: () => undefined },
            { type: "separator" },
            { label: "Delete shelf", icon: <Trash2 aria-hidden="true" />, danger: true, onSelect: () => setDialog(true) },
          ]}
        />
        <Menu
          align="start"
          trigger={(props) => (
            <Button {...props} iconEnd={<MoreHorizontal aria-hidden="true" />}>
              Sort
            </Button>
          )}
          items={[
            { label: "Recently updated", onSelect: () => undefined },
            { label: "Title", onSelect: () => undefined },
            { label: "Date added", onSelect: () => undefined },
          ]}
        />
        <Popover
          label="Filters"
          trigger={(props) => (
            <Button {...props} icon={<Filter aria-hidden="true" />}>
              Filters
            </Button>
          )}
        >
          {(close) => (
            <div className="gallery__stack">
              <Switch label="Unread only" checked={unreadOnly} onChange={setUnreadOnly} />
              <Button size="sm" variant="primary" onClick={close}>
                Done
              </Button>
            </div>
          )}
        </Popover>
      </Section>

      <Section title="Dialog, sheet, toast">
        <Button variant="danger" onClick={() => setDialog(true)}>
          Delete shelf…
        </Button>
        <Button onClick={() => setSheet("auto")}>Open sheet (auto)</Button>
        <Button onClick={() => setSheet("bottom")}>Bottom sheet</Button>
        <Button onClick={() => setSheet("side")}>Side drawer</Button>
        <Button onClick={() => addToast("Saved to Comfort reads", "success", undefined, { action: { label: "Undo", onClick: () => undefined } })}>
          Toast
        </Button>
        <Button onClick={() => addToast("Couldn't reach FanFiction.net", "error")}>Error toast</Button>
        <Dialog
          open={dialog}
          onClose={() => setDialog(false)}
          title="Delete shelf 'Comfort reads'?"
          description="The 12 stories stay in your library."
          actions={
            <>
              <Button onClick={() => setDialog(false)}>Cancel</Button>
              <Button variant="danger" onClick={() => setDialog(false)}>
                Delete shelf
              </Button>
            </>
          }
        />
        <Sheet
          open={sheet !== null}
          variant={sheet ?? "auto"}
          onClose={() => setSheet(null)}
          title="Text settings"
          footer={<Button variant="primary" onClick={() => setSheet(null)}>Done</Button>}
        >
          <div className="gallery__stack">
            <Input label="Font size" type="number" defaultValue={19} />
            <Switch label="Justify text" checked={false} onChange={() => undefined} />
          </div>
        </Sheet>
      </Section>

      <Section title="Tabs">
        <div className="gallery__stack">
          <Tabs
            label="Story sections"
            value={tab}
            onChange={setTab}
            items={[
              { value: "overview", label: "Overview", panel: <p>Overview panel.</p> },
              { value: "chapters", label: "Chapters", panel: <p>Chapters panel.</p> },
              { value: "notes", label: "Notes", panel: <p>Notes panel.</p> },
            ]}
          />
        </div>
      </Section>

      <Section title="Banners">
        <div className="gallery__stack">
          <Banner tone="info">Offline. Showing downloaded chapters only.</Banner>
          <Banner tone="warning" action={<Button size="sm">Retry now</Button>}>
            Can't reach FanFiction.net. Retrying in 30 s.
          </Banner>
          <Banner tone="danger" onDismiss={() => undefined}>
            3 downloads failed.
          </Banner>
          <Banner tone="success">Backup finished.</Banner>
        </div>
      </Section>

      <Section title="Covers">
        <Cover title="The Wandering Inn" author="pirateaba" size={112} />
        <Cover title="Mother of Learning" author="nobody103" size={112} />
        <Cover title="Worm" size={72} />
        <Cover title="Beware of Chicken" size={48} />
        <Cover title="Broken image" src="/does-not-exist.png" size={112} alt="Broken image" />
      </Section>

      <Section title="Cards, list rows, progress">
        <div className="gallery__grid">
          {TITLES.slice(0, 3).map((title, i) => (
            <Card key={title} as="article" interactive media={<Cover title={title} size="fill" />}>
              <h3 className="text-lg">
                <a href="#cards" className="ui-stretched-link">
                  {title}
                </a>
              </h3>
              <p className="text-sm text-muted">Chapter {12 * (i + 1)} of 98</p>
              <Progress label={`Reading progress for ${title}`} value={12 * (i + 1)} max={98} valueText={`Chapter ${12 * (i + 1)} of 98`} />
            </Card>
          ))}
        </div>
        <ul className="gallery__stack" style={{ padding: 0 }}>
          {TITLES.slice(3).map((title, i) => (
            <ListRow
              as="li"
              key={title}
              to="#rows"
              selected={i === 0}
              media={<Cover title={title} size={48} />}
              title={title}
              meta={<>3 new chapters · <Badge tone="info">New</Badge></>}
              actions={<IconButton label={`Read ${title}`} icon={<BookOpen />} size="sm" />}
            />
          ))}
        </ul>
        <div className="gallery__stack">
          <Progress label="Download" value={98} max={98} valueText="Done: 98 of 98 chapters" showText />
          <Progress label="Checking sources" valueText="Checking sources" showText />
        </div>
      </Section>

      <Section title="Empty state and skeleton">
        <div className="gallery__grid">
          <Card>
            <EmptyState
              level={3}
              icon={<BookOpen />}
              title="No stories on this shelf yet"
              description="Add stories from your library or from Discover."
              action={<Button variant="primary">Find stories</Button>}
            />
          </Card>
          <SkeletonGroup className="gallery__stack">
            <Skeleton type="cover" style={{ width: 112 }} />
            <Skeleton type="line" />
            <Skeleton type="line" style={{ width: "60%" }} />
            <Skeleton type="row" />
          </SkeletonGroup>
        </div>
      </Section>
    </>
  );
}
