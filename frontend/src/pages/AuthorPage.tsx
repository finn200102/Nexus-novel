import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ExternalLink, UserX } from "lucide-react";
import { Badge, EmptyState, ListRow, PageHeader, Skeleton, SkeletonGroup } from "../components/ui";
import FollowToggle from "../components/follow/FollowToggle";
import { siteLabel } from "../components/story/storyModel";
import { followService, type AuthorPageData, type AuthorProfile, type AuthorWork } from "../services/followService";
import { getUserFacingError } from "../services/apiClient";
import { usePageTitle } from "../hooks/usePageTitle";
import "../styles/follow.css";

const workLink = (work: AuthorWork): { to?: string; href?: string } =>
  work.metadata_id ? { to: `/story/${work.metadata_id}` } : work.url ? { href: work.url } : {};

const ProfileSection: React.FC<{ profile: AuthorProfile; onChange: (profile: AuthorProfile) => void }> = ({ profile, onChange }) => {
  const headingId = `author-profile-${profile.id}`;
  return (
    <section className="follow-section" aria-labelledby={headingId}>
      <div className="follow-section__header">
        <h2 id={headingId} className="text-lg">
          {profile.name} <Badge>{siteLabel(profile.site) ?? profile.site}</Badge>
        </h2>
        {profile.followable && profile.key && (
          <FollowToggle
            label="Follow author"
            request={{ kind: "author", site: profile.site, key: profile.key, name: profile.name, metadata_author_id: profile.id }}
            followId={profile.follow_id}
            onChange={(followId) => onChange({ ...profile, follow_id: followId })}
          />
        )}
      </div>
      {profile.works.length === 0 ? (
        <p className="follow-section__empty">
          {profile.follow_id ? "Works appear here after the next check of this author page." : "No works in the catalog yet."}
        </p>
      ) : (
        <ul className="follow-list">
          {profile.works.map((work, index) => {
            const link = workLink(work);
            return (
              <ListRow
                key={`${work.metadata_id ?? work.url ?? index}`}
                as="li"
                title={work.title ?? "Untitled"}
                meta={[work.status, siteLabel(work.site)].filter(Boolean).join(" · ")}
                to={link.to}
                actions={
                  !link.to && link.href ? (
                    <a href={link.href} target="_blank" rel="noopener noreferrer" aria-label={`Open ${work.title ?? "work"} on ${siteLabel(work.site) ?? "the source site"}`}>
                      <ExternalLink aria-hidden size={18} />
                    </a>
                  ) : undefined
                }
              />
            );
          })}
        </ul>
      )}
    </section>
  );
};

/** An author's works across sites (same name on each site), with a follow toggle per site. */
const AuthorPage: React.FC = () => {
  const { authorId } = useParams<{ authorId: string }>();
  const id = authorId && /^\d+$/.test(authorId) ? Number(authorId) : null;
  const [data, setData] = useState<AuthorPageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loading = id !== null && !data && !error;

  usePageTitle(data?.name ?? (error ? "Author not found" : null), { back: { to: "/library/following", label: "Following" } });

  useEffect(() => {
    if (id === null) return;
    let cancelled = false;
    followService
      .author(id)
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(getUserFacingError(err, "Could not load this author.")));
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (id === null || error) {
    return <EmptyState icon={<UserX aria-hidden />} title="Author not found" description={error ?? undefined} />;
  }
  if (loading || !data) {
    return (
      <SkeletonGroup label="Loading author">
        <Skeleton type="line" style={{ width: "40%" }} />
        <Skeleton type="line" />
        <Skeleton type="line" />
      </SkeletonGroup>
    );
  }
  const total = data.profiles.reduce((sum, profile) => sum + profile.works.length, 0);
  return (
    <div className="follow-page">
      <PageHeader
        title={data.name}
        description={`${total} ${total === 1 ? "work" : "works"} on ${data.profiles.length} ${data.profiles.length === 1 ? "site" : "sites"}`}
      />
      {data.profiles.map((profile) => (
        <ProfileSection
          key={profile.id}
          profile={profile}
          onChange={(next) => setData({ ...data, profiles: data.profiles.map((item) => (item.id === next.id ? next : item)) })}
        />
      ))}
    </div>
  );
};

export default AuthorPage;
