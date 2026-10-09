import React, { useCallback, useEffect, useState } from "react";
import { Users } from "lucide-react";
import { Badge, EmptyState, ListRow, PageHeader, Skeleton, SkeletonGroup } from "../components/ui";
import FollowToggle from "../components/follow/FollowToggle";
import { siteLabel } from "../components/story/storyModel";
import { followService, type CreatorFollow } from "../services/followService";
import { getUserFacingError } from "../services/apiClient";
import { usePageTitle } from "../hooks/usePageTitle";
import "../styles/follow.css";

const KIND_TITLES = { author: "Authors", series: "Series" } as const;

/** Followed authors and series (`/library/following`). */
const FollowingPage: React.FC = () => {
  const [follows, setFollows] = useState<CreatorFollow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  usePageTitle("Following", { back: { to: "/library", label: "Back to Library" } });

  const load = useCallback(() => {
    followService
      .list()
      .then(setFollows)
      .catch((err) => setError(getUserFacingError(err, "Could not load who you follow.")));
  }, []);
  useEffect(load, [load]);

  if (error) return <EmptyState icon={<Users aria-hidden />} title="Could not load" description={error} />;
  if (!follows) {
    return (
      <SkeletonGroup label="Loading follows">
        <Skeleton type="row" />
        <Skeleton type="row" />
      </SkeletonGroup>
    );
  }

  return (
    <div className="follow-page">
      <PageHeader title="Following" description="New works by these authors and new entries in these series show up in Updates." />
      {follows.length === 0 ? (
        <EmptyState
          icon={<Users aria-hidden />}
          title="Not following anyone yet"
          description="Use “Follow author” on a story page to hear about an author's next story."
        />
      ) : (
        (["author", "series"] as const).map((kind) => {
          const rows = follows.filter((row) => row.kind === kind);
          if (rows.length === 0) return null;
          return (
            <section key={kind} className="follow-section" aria-labelledby={`following-${kind}`}>
              <h2 id={`following-${kind}`} className="text-lg">{KIND_TITLES[kind]}</h2>
              <ul className="follow-list">
                {rows.map((row) => (
                  <ListRow
                    key={row.id}
                    as="li"
                    title={row.name ?? row.key}
                    meta={<Badge>{siteLabel(row.site) ?? row.site}</Badge>}
                    to={row.kind === "author" && row.metadata_author_id ? `/authors/${row.metadata_author_id}` : undefined}
                    actions={
                      <FollowToggle
                        request={{ kind: row.kind, site: row.site, key: row.key, name: row.name }}
                        followId={row.id}
                        onChange={(followId) => {
                          if (followId === null) setFollows(follows.filter((item) => item.id !== row.id));
                        }}
                      />
                    }
                  />
                ))}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
};

export default FollowingPage;
