import { useEffect, useRef } from "react";

interface AudioControls {
  active: boolean;
  playing: boolean;
  title: string;
  onPlay: () => void;
  onPause: () => void;
  onStop: () => void;
  onSeek?: (seconds: number, relative: boolean) => void;
}

/** Expose the same player actions to headphones and device media controls. */
export function useAudioMediaSession(controls: AudioControls) {
  const current = useRef(controls);
  current.current = controls;
  const seekable = Boolean(controls.onSeek);
  useEffect(() => {
    if (!controls.active || !navigator.mediaSession) return;
    const session = navigator.mediaSession;
    if (typeof MediaMetadata !== "undefined") session.metadata = new MediaMetadata({ title: controls.title, artist: "Nexus" });
    const handlers: Partial<Record<MediaSessionAction, MediaSessionActionHandler>> = {
      play: () => current.current.onPlay(), pause: () => current.current.onPause(), stop: () => current.current.onStop(),
      ...(seekable ? {
        seekbackward: (event: MediaSessionActionDetails) => current.current.onSeek?.(-(event.seekOffset ?? 15), true),
        seekforward: (event: MediaSessionActionDetails) => current.current.onSeek?.(event.seekOffset ?? 15, true),
        seekto: (event: MediaSessionActionDetails) => { if (event.seekTime !== undefined) current.current.onSeek?.(event.seekTime, false); },
      } : {}),
    };
    const registered: MediaSessionAction[] = [];
    for (const [action, handler] of Object.entries(handlers)) {
      try { session.setActionHandler(action as MediaSessionAction, handler); registered.push(action as MediaSessionAction); }
      catch { /* Some browsers support only a subset of device actions. */ }
    }
    return () => {
      for (const action of registered) { try { session.setActionHandler(action, null); } catch { /* unsupported */ } }
      session.metadata = null;
      session.playbackState = "none";
    };
  }, [controls.active, controls.title, seekable]);
  useEffect(() => {
    if (navigator.mediaSession && controls.active) navigator.mediaSession.playbackState = controls.playing ? "playing" : "paused";
  }, [controls.active, controls.playing]);
}
