import React, { useState } from "react";
import { UserCheck, UserPlus } from "lucide-react";
import { Button } from "../ui";
import { followService, type FollowRequest } from "../../services/followService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";

interface FollowToggleProps {
  /** What to follow; null while unknown (the button is then disabled). */
  request: FollowRequest | null;
  followId: number | null;
  onChange: (followId: number | null) => void;
  /** Visible label for the "follow" state, e.g. "Follow author". */
  label?: string;
  size?: "sm" | "md";
}

/** Follow / Following button for an author page or a series. */
const FollowToggle: React.FC<FollowToggleProps> = ({ request, followId, onChange, label = "Follow", size = "sm" }) => {
  const { addToast } = useToast();
  const [busy, setBusy] = useState(false);
  const following = followId !== null;

  const toggle = async () => {
    if (!request) return;
    setBusy(true);
    try {
      if (following) {
        await followService.unfollow(followId);
        onChange(null);
      } else {
        const created = await followService.follow(request);
        onChange(created.id);
        addToast(`New works from ${request.name ?? "this follow"} will show up in Updates.`, "success");
      }
    } catch (error) {
      addToast(getUserFacingError(error, following ? "Could not unfollow. Try again." : "Could not follow. Try again."), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      size={size}
      variant={following ? "secondary" : "ghost"}
      icon={following ? <UserCheck aria-hidden /> : <UserPlus aria-hidden />}
      aria-pressed={following}
      loading={busy}
      disabled={!request}
      onClick={() => void toggle()}
    >
      {following ? "Following" : label}
    </Button>
  );
};

export default FollowToggle;
