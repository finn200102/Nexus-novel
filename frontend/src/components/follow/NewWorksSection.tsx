import React, { useCallback, useEffect, useState } from "react";
import { Button, ListRow } from "../ui";
import { siteLabel } from "../story/storyModel";
import { followService, type NewWork } from "../../services/followService";
import "../../styles/follow.css";

/** "New from authors you follow": unread new works and series entries, in Updates. */
const NewWorksSection: React.FC = () => {
  const [works, setWorks] = useState<NewWork[]>([]);

  const load = useCallback(() => {
    followService.newWorks().then(setWorks).catch(() => setWorks([]));
  }, []);
  useEffect(load, [load]);

  if (works.length === 0) return null;

  const dismiss = async (ids?: number[]) => {
    await followService.markNewWorksRead(ids).catch(() => undefined);
    load();
  };

  return (
    <section className="follow-section" aria-labelledby="new-works-heading">
      <div className="follow-section__header">
        <h2 id="new-works-heading" className="text-lg">New from authors and series you follow</h2>
        <Button size="sm" variant="ghost" onClick={() => void dismiss()}>Mark all seen</Button>
      </div>
      <ul className="follow-list">
        {works.map((work) => (
          <ListRow
            key={work.id}
            as="li"
            title={work.title ?? "New work"}
            meta={[work.follow?.kind === "series" ? `In ${work.follow?.name ?? "a series"}` : `By ${work.follow?.name ?? work.author ?? "an author you follow"}`, siteLabel(work.site)]
              .filter(Boolean)
              .join(" · ")}
            to={work.metadata_id ? `/story/${work.metadata_id}` : undefined}
            onClick={work.metadata_id ? () => void followService.markNewWorksRead([work.id]) : undefined}
            actions={
              <>
                {!work.metadata_id && work.url && <a href={work.url} target="_blank" rel="noopener noreferrer">Open</a>}
                <Button size="sm" variant="ghost" onClick={() => void dismiss([work.id])} aria-label={`Mark ${work.title ?? "work"} seen`}>
                  Seen
                </Button>
              </>
            }
          />
        ))}
      </ul>
    </section>
  );
};

export default NewWorksSection;
