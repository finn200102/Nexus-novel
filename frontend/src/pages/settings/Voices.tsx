import PronunciationEditor from "../../components/reader/PronunciationEditor";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { PageHeader } from "../../components/ui";
import { NarratorVoices } from "../../components/reader/NarratorVoices";
import { accountStorage, onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { voiceService, type NarratorVoice } from "../../services/voiceService";
import { usePageTitle } from "../../hooks/usePageTitle";
import { SETTINGS_BACK } from "./settingsNav";

function AccountVoices() {
  const generation = storageGeneration();
  const [selected, setSelected] = useState<number | null>(() => Number(accountStorage.getItem("nexus-reader-narrator-id")) || null);
  const revision = useRef(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true;
    voiceService.getDefault().then(async value => {
      if (!active || generation !== storageGeneration()) return;
      // Preserve a previously selected local narrator when this account has
      // never saved a server default. An explicit server reset wins otherwise.
      const previous=Number(accountStorage.getItem("nexus-reader-narrator-id")) || null;
      if (value.revision===0 && value.voice_profile_id===null && previous) {
        const voices=await voiceService.list();
        if (!active || generation!==storageGeneration()) return;
        if (voices.some(voice=>voice.id===previous && voice.status==="completed")) {
          try {value=await voiceService.setDefault(previous,0);}
          catch {value=await voiceService.getDefault();}
        }
      }
      if (!active || generation!==storageGeneration()) return;
      revision.current = value.revision;
      setSelected(value.voice_profile_id);
      if (value.voice_profile_id) accountStorage.setItem("nexus-reader-narrator-id", String(value.voice_profile_id));
      else accountStorage.removeItem("nexus-reader-narrator-id");
    }).catch(() => {if (active && generation === storageGeneration()) setError("The default narrator could not be loaded. Check your connection before changing it.");})
      .finally(() => {if (active && generation === storageGeneration()) setLoading(false);});
    return () => {active = false;};
  }, [generation]);
  const select = async (voice: NarratorVoice | null) => {
    if (saving) return;
    setSaving(true); setError("");
    try {
      const value = await voiceService.setDefault(voice?.id ?? null, revision.current);
      if (generation !== storageGeneration()) return;
      revision.current = value.revision;
      setSelected(voice?.id ?? null);
      if (voice) {
        accountStorage.setItem("nexus-reader-narrator-id", String(voice.id));
        accountStorage.setItem("nexus-reader-tts-engine", "openai_compatible");
        accountStorage.setItem("nexus-reader-tts-preset", "qwen3_clone");
        accountStorage.setItem("nexus-reader-tts-execution", "server");
      } else {
        accountStorage.removeItem("nexus-reader-narrator-id");
        if (accountStorage.getItem("nexus-reader-tts-preset") === "qwen3_clone") accountStorage.setItem("nexus-reader-tts-engine", "native");
      }
    } catch {
      if (generation === storageGeneration()) setError("The default narrator could not be saved. Reload this page if it changed on another device.");
    } finally {if (generation === storageGeneration()) setSaving(false);}
  };
  return <>
    {loading ? <p role="status">Loading your narrator settings…</p> : <NarratorVoices selected={selected} onSelect={voice => void select(voice)} />}
    {saving && <p role="status">Saving default narrator…</p>}
    {error && <p role="alert">{error}</p>}
  </>;
}

export default function Voices() {
  usePageTitle("Narrator voices", { back: SETTINGS_BACK });
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <>
    <PageHeader title="Narrator voices" description="Create and manage your private narrator voices for all your stories." />
    <p>Upload a recording here, preview the prepared voice, then choose Use as narrator. Your selected narrator follows your account across devices and is available when generating audio for any story. Existing recordings keep their original narrator.</p>
    <AccountVoices key={generation} />
    <PronunciationEditor />
  </>;
}
