import React, { useEffect, useState } from "react";
import { followService, type AuthorProfile } from "../../services/followService";
import FollowToggle from "./FollowToggle";

interface FollowAuthorButtonProps {
  /** Catalog (metadata) author id of the story's author. */
  authorId: number;
}

/** "Follow author" on the story page; hidden when the author's site has no author pages. */
const FollowAuthorButton: React.FC<FollowAuthorButtonProps> = ({ authorId }) => {
  const [profile, setProfile] = useState<AuthorProfile | null>(null);

  useEffect(() => {
    let cancelled = false;
    followService
      .author(authorId)
      .then((data) => {
        if (!cancelled) setProfile(data.profiles.find((item) => item.id === authorId) ?? null);
      })
      .catch(() => {
        if (!cancelled) setProfile(null);
      });
    return () => {
      cancelled = true;
    };
  }, [authorId]);

  if (!profile?.followable || !profile.key) return null;
  return (
    <FollowToggle
      label="Follow author"
      request={{ kind: "author", site: profile.site, key: profile.key, name: profile.name, metadata_author_id: profile.id }}
      followId={profile.follow_id}
      onChange={(followId) => setProfile({ ...profile, follow_id: followId })}
    />
  );
};

export default FollowAuthorButton;
