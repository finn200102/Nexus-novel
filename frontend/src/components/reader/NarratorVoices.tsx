import { isAxiosError } from "axios";
import { getUserFacingError } from "../../services/apiClient";
import { useEffect, useRef, useState } from "react";
import { Button, Input, Select } from "../ui";
import { NarratorVoice, voiceService } from "../../services/voiceService";
import { storageGeneration } from "../../services/accountStorage";

export function NarratorVoices({selected, onSelect}: {selected: number | null; onSelect: (voice: NarratorVoice | null) => void}) {
  const [voices, setVoices] = useState<NarratorVoice[]>([]);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [languages, setLanguages] = useState<string[]>(["English"]);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("English");
  const [transcript, setTranscript] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [recordingPreview, setRecordingPreview] = useState<string | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [cropping, setCropping] = useState(false);
  const [excerptStart, setExcerptStart] = useState("0");
  const [excerptEnd, setExcerptEnd] = useState("15");
  const [transcriptNotice, setTranscriptNotice] = useState("");
  const recordingAudio = useRef<HTMLAudioElement | null>(null);
  const recordingUrl = useRef<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const previewRef = useRef<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const previewRequest = useRef(0);
  const mounted = useRef(false);
  const generation = storageGeneration();
  const current = () => mounted.current && storageGeneration() === generation;
  const clearPreview = () => { previewRequest.current += 1; audioRef.current?.pause(); if (previewRef.current) URL.revokeObjectURL(previewRef.current); previewRef.current = null; setPreview(null); };
  useEffect(() => {
    mounted.current = true;
    const refresh = () => voiceService.list().then((rows) => { if (mounted.current && generation === storageGeneration()) setVoices(rows); }).catch(() => undefined);
    voiceService.capabilities().then((data) => { if (mounted.current && generation === storageGeneration()) {setConfigured(data.configured); setLanguages(data.languages);} }).catch(() => {if (mounted.current && generation === storageGeneration()) setConfigured(false);});
    void refresh();
    const timer = window.setInterval(() => {if (generation === storageGeneration()) void refresh();}, 3000);
    return () => {mounted.current = false; previewRequest.current += 1; window.clearInterval(timer); if (previewRef.current) URL.revokeObjectURL(previewRef.current);};
  }, [generation]);

  useEffect(() => {const audio = audioRef.current; return () => {audio?.pause();};}, [preview]);

  useEffect(() => {
    if (!file || file.size > 12 * 1024 * 1024 || typeof URL.createObjectURL !== "function") return;
    const url = URL.createObjectURL(file), player = recordingAudio;
    recordingUrl.current = url; setRecordingPreview(url);
    return () => { player.current?.pause(); URL.revokeObjectURL(url); if (recordingUrl.current === url) recordingUrl.current = null; };
  }, [file, generation]);
  useEffect(() => {
    const audio = recordingAudio.current;
    return () => audio?.pause();
  }, [recordingPreview]);
  const clearTranscriptForExcerpt = () => {
    if (transcript.trim()) setTranscriptNotice("The excerpt changed. Enter only the words in the selected excerpt, or leave the transcript blank for local transcription.");
    setTranscript("");
  };
  const chooseFile = (next: File | null) => {
    recordingAudio.current?.pause(); setFile(next); setRecordingPreview(null); setDuration(null);
    setCropping(false); setExcerptStart("0"); setExcerptEnd("15"); setTranscript(""); setTranscriptNotice("");
    setError(next && next.size > 12 * 1024 * 1024 ? "Choose a recording smaller than 12 MB." : "");
  };
  const start = Number(excerptStart), end = Number(excerptEnd);
  const invalidExcerpt = cropping && (!excerptStart.trim() || !excerptEnd.trim() || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || start > 3600 || end - start < 3 || end - start > 30 || duration !== null && end > duration + 0.05);
  const tooShort = duration !== null && duration < 3;
  const loadMetadata = (event: React.SyntheticEvent<HTMLAudioElement>) => {
    if (!current() || event.currentTarget.src !== recordingUrl.current) return;
    const seconds = event.currentTarget.duration;
    if (!Number.isFinite(seconds) || seconds <= 0 || duration !== null) return;
    setDuration(seconds);
    if (seconds > 30 && !cropping) { setCropping(true); setExcerptStart("0"); setExcerptEnd("15"); clearTranscriptForExcerpt(); }
    else if (!cropping) setExcerptEnd(String(Math.round(seconds * 1000) / 1000));
  };
  const playExcerpt = async () => {
    const audio = recordingAudio.current;
    if (!audio || invalidExcerpt || tooShort) return;
    try { audio.currentTime = cropping ? start : 0; await audio.play(); }
    catch { if (current()) setError("The recording could not be previewed here. You can still select an excerpt and let Nexus validate the audio."); }
  };

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!file || !name.trim()) return;
    if (file.size > 12 * 1024 * 1024) {setError("Choose a recording smaller than 12 MB."); return;}
    if (tooShort || invalidExcerpt) {setError("Choose a 3–30-second excerpt within the recording, starting no later than 3600 seconds."); return;}
    setBusy(true); setError("");
    try {
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file);
      });
      if (!current()) return;
      const voice = await voiceService.upload({name: name.trim(), audio_base64: data, transcript, language,
        ...(cropping ? { excerpt_start_seconds: start, excerpt_duration_seconds: Math.round((end - start) * 1000) / 1000 } : {}),
      });
      if (current()) {setVoices((rows) => [voice, ...rows]); setName(""); chooseFile(null); if (fileInput.current) fileInput.current.value = "";}
    } catch (uploadError) {
      if (current()) {
        const fallback = "The recording could not be uploaded. Your file is still selected; check your connection and try again.";
        if (isAxiosError(uploadError) && uploadError.response?.status === 413) setError("Nexus rejected this upload as too large. Your file is still selected. The server’s narrator upload limit needs to be increased.");
        else {
          const details = isAxiosError(uploadError) ? uploadError.response?.data?.detail : null;
          const validation = Array.isArray(details) ? details.slice(0, 5).map(issue => typeof issue?.msg === "string" ? issue.msg : "").filter(Boolean).join(" ") : "";
          setError(validation || getUserFacingError(uploadError, fallback));
        }
      }
    }
    finally {if (current()) setBusy(false);}
  }

  async function play(voice: NarratorVoice) {
    setError(""); clearPreview();
    const request = previewRequest.current;
    try {
      const blob = await voiceService.preview(voice.id);
      if (current() && request === previewRequest.current) {const url = URL.createObjectURL(blob); previewRef.current = url; setPreview(url);}
    } catch {if (current()) setError("The preview could not be loaded.");}
  }
  async function remove(voice: NarratorVoice) {
    clearPreview();
    try {
      await voiceService.remove(voice.id);
      if (current()) {clearPreview();setVoices((rows) => rows.filter((row) => row.id !== voice.id)); if (selected === voice.id) onSelect(null);}
    } catch {if (current()) setError("The narrator could not be removed.");}
  }
  async function retry(voice: NarratorVoice) {
    try {const result = await voiceService.retry(voice.id); if (current()) setVoices((rows) => rows.map((row) => row.id === result.id ? result : row));}
    catch {if (current()) setError("The narrator could not be retried.");}
  }
  return <section className="reader-narrators" aria-label="My narrator voices">
    <h3>My narrator voices</h3>
    <p className="text-sm text-muted">Choose a recording of one clear voice. You can select a 3–30-second excerpt from a longer file; 5–15 seconds works best. Your recording and narration stay on this installation. Use a voice you have permission to use.</p>
    {configured === false && <p role="status">Local voice cloning needs to be enabled by your administrator.</p>}
    {voices.map((voice) => <div key={voice.id} className="reader-narrators__voice">
      <strong>{voice.name}</strong><span className="text-sm"> · {voice.language} · {voice.status === "completed" ? "Ready" : voice.status === "failed" ? "Needs attention" : "Preparing locally…"}</span>
      {voice.error && <p className="text-sm" role="status">{voice.error}</p>}
      <div className="reader-listen-settings__actions">
        {voice.status === "completed" && <Button size="sm" onClick={() => onSelect(voice)}>{selected === voice.id ? "Selected narrator" : "Use as narrator"}</Button>}
        {voice.preview_ready && <Button size="sm" onClick={() => void play(voice)}>Listen to {voice.name}</Button>}
        {["failed", "retry_wait"].includes(voice.status) && <Button size="sm" onClick={() => void retry(voice)}>Retry preparation</Button>}
        <Button size="sm" variant="danger" onClick={() => void remove(voice)}>Delete {voice.name}</Button>
      </div>
    </div>)}
    {preview && <audio ref={audioRef} controls autoPlay src={preview} aria-label="Cloned narrator preview" />}
    {configured && <form onSubmit={(event) => void upload(event)} className="reader-narrators__form">
      <Input label="Narrator name" disabled={busy} maxLength={120} value={name} onChange={(event) => setName(event.target.value)} required />
      <Input ref={fileInput} label="Voice recording" disabled={busy} type="file" accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.aiff,.webm" onChange={(event) => chooseFile(event.target.files?.[0] || null)} required />
      {file && <div>
        {recordingPreview && <audio key={recordingPreview} ref={recordingAudio} controls preload="metadata" src={recordingPreview} aria-label="Selected recording preview" onLoadedMetadata={loadMetadata} onDurationChange={loadMetadata} onPlay={event => {
          if (cropping && !invalidExcerpt && (event.currentTarget.currentTime < start || event.currentTarget.currentTime >= end)) event.currentTarget.currentTime = start;
        }} onTimeUpdate={event => { if (cropping && !invalidExcerpt && event.currentTarget.currentTime >= end) { event.currentTarget.pause(); event.currentTarget.currentTime = start; } }} />}
        {duration !== null && <p className="text-sm">Recording length: {duration.toFixed(1)} seconds.</p>}
        <label className="ui-check"><input type="checkbox" checked={cropping} disabled={busy || duration !== null && duration > 30} onChange={event => {
          clearTranscriptForExcerpt(); setCropping(event.target.checked); setExcerptStart("0"); setExcerptEnd(String(Math.min(duration ?? 15, 15)));
        }} /><span>Use a selected excerpt</span></label>
        {cropping && <>
          <Input label="Excerpt start (seconds)" type="number" min="0" max="3600" step="0.1" value={excerptStart} disabled={busy} onChange={event => { clearTranscriptForExcerpt(); setExcerptStart(event.target.value); }} />
          <Input label="Excerpt end (seconds)" type="number" min="3" max={duration ?? 3630} step="0.1" value={excerptEnd} disabled={busy} onChange={event => { clearTranscriptForExcerpt(); setExcerptEnd(event.target.value); }} />
          <p className="text-sm">Cloning uses only the selected excerpt. The first 15 seconds are selected automatically for long recordings; choose a clear passage with one speaker.</p>
          {invalidExcerpt && <p role="status">Select 3–30 seconds within the recording.</p>}
        </>}
        {tooShort && <p role="status">This recording is shorter than 3 seconds. Choose a longer recording.</p>}
        {recordingPreview && <Button disabled={busy || invalidExcerpt || tooShort} onClick={() => void playExcerpt()}>{cropping ? "Play selected excerpt" : "Preview recording"}</Button>}
      </div>}
      <Select label="Recording language" disabled={busy} value={language} onChange={(event) => setLanguage(event.target.value)} options={languages.map((value) => ({value, label: value}))} />
      <Input label={cropping ? "Selected excerpt transcript (optional)" : "Recording transcript (optional)"} disabled={busy} hint={cropping ? "Only the exact words between the selected start and end times. Leave blank to transcribe the excerpt locally." : "The exact words in the recording. Leave blank to transcribe locally."} maxLength={4000} value={transcript} onChange={(event) => setTranscript(event.target.value)} />
      {transcriptNotice && <p role="status">{transcriptNotice}</p>}
      <Button type="submit" disabled={busy || !file || file.size > 12 * 1024 * 1024 || !name.trim() || invalidExcerpt || tooShort}>{busy ? "Uploading…" : "Create narrator voice"}</Button>
      <p className="text-sm text-muted">First use may take several minutes to download the local models. Deleting a voice removes its recording and preview and cancels its unfinished jobs; completed chapter audio remains separately removable.</p>
    </form>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
