import { chapterIdentity, expectedChapterIdentity, observeChapterIdentity, assertCurrentChapterIdentity, ChapterManifestChangedError, type ChapterIdentity } from "../../services/chapterIdentity";
import { getUserFacingError } from "../../services/apiClient";
import PronunciationEditor from "../reader/PronunciationEditor";
import type {PronunciationSnapshot} from "../../services/pronunciationService";
import StoryAudioExports from "./StoryAudioExports";
import StorySavedRecordings from './StorySavedRecordings';
import "./StoryAudio.css";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { Banner, Button, Checkbox, Dialog, Input, Select } from "../ui";
import { audioService, type StoryAudioBatch, type StoryAudioOverview, type ServerAudioJob } from "../../services/audioService";
import { voiceService, type NarratorVoice } from "../../services/voiceService";
import { TTS_PROVIDER_PRESETS, ttsService, type OpenAICompatibleTtsConfig, type TtsProviderPresetId } from "../../services/ttsService";
import { browserAudioQueue, type BrowserAudioRow } from "../../services/browserAudioQueue";
import { chapterAudioStore } from "../../services/offlineReaderStore";
import { accountStorage, onAccountStorageChange, storageGeneration } from "../../services/accountStorage";

const PAGE_SIZE = 50;
class AudioSelectionError extends Error {}
type ProviderId = TtsProviderPresetId | "qwen3_clone";
const presetUrl = (id: ProviderId, mode: "browser" | "server") => {
  const url = TTS_PROVIDER_PRESETS.find(preset => preset.id === id)?.config.baseUrl || "";
  return mode === "server" ? url.replace("localhost", "host.docker.internal") : url;
};
const savedPreset = (): ProviderId => {
  const id = accountStorage.getItem("nexus-reader-tts-preset");
  return id === "qwen3_clone" || TTS_PROVIDER_PRESETS.some(preset => preset.id === id) ? id as ProviderId : "kokoro_mps";
};
const activeJob = (job: ServerAudioJob | null) => Boolean(job && ["queued", "processing", "retry_wait"].includes(job.status));
const outcomeLabels: Record<StoryAudioBatch["outcomes"][number]["outcome"], string> = {
  queued: "Queued", already_ready: "Already ready", already_queued: "Already queued", unavailable: "Download the chapter first", needs_retry: "Use Retry on this chapter",
};

function StoryAudioContents({ novelId, libraryId }: { novelId: number; libraryId: number }) {
  const generation = storageGeneration();
  const mounted = useRef(false);
  const [pronunciation, setPronunciation] = useState<PronunciationSnapshot | null>(null);
  const [showExports, setShowExports] = useState(false);
  const [showSaved,setShowSaved]=useState(false);
  const [overview, setOverview] = useState<StoryAudioOverview | null>(null);
  const [voices, setVoices] = useState<NarratorVoice[]>([]);
  const [voiceId, setVoiceId] = useState("");
  const [providerId, setProviderId] = useState<ProviderId>(savedPreset);
  const [execution, setExecution] = useState<"browser" | "server">(() => accountStorage.getItem("nexus-reader-tts-execution") === "server" ? "server" : "browser");
  const [providerConfig, setProviderConfig] = useState<OpenAICompatibleTtsConfig>(() => {
    const id = savedPreset();
    const preset = TTS_PROVIDER_PRESETS.find(value => value.id === id) || TTS_PROVIDER_PRESETS[0];
    const mode = accountStorage.getItem("nexus-reader-tts-execution") === "server" ? "server" : "browser";
    return { baseUrl: accountStorage.getItem("nexus-reader-tts-url") ?? presetUrl(id, mode),
      model: accountStorage.getItem("nexus-reader-tts-model") ?? preset.config.model,
      voice: accountStorage.getItem("nexus-reader-tts-provider-voice") ?? preset.config.voice,
      languageCode: accountStorage.getItem("nexus-reader-tts-language") ?? preset.config.languageCode,
      apiKey: accountStorage.getItem("nexus-reader-tts-key") || "" };
  });
  const providerChanged = useRef(false);
  const [diagnostic, setDiagnostic] = useState("");
  const queue = useSyncExternalStore(browserAudioQueue.subscribe, browserAudioQueue.getSnapshot);
  const browserRows = queue.generation === generation ? queue.rows.filter(row => row.novelId === novelId) : [];
  const [page, setPage] = useState(0);
  const chosenNarrator = useRef(false);
  const [selected, setSelected] = useState<number[]>([]);
  const chapterBindings=useRef(new Map<number,{identity:ChapterIdentity;sourceVersion:string|null}>());
  const selectedBindings=useRef(new Map<number,{identity:ChapterIdentity;sourceVersion:string|null}>());
  const [rangeStart, setRangeStart] = useState("1");
  const [rangeEnd, setRangeEnd] = useState("1");
  const [includeNotes, setIncludeNotes] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const [results, setResults] = useState<StoryAudioBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [removeChapter, setRemoveChapter] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ src: string; chapter: number } | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const previewUrl = useRef<string | null>(null);
  const previewRequest = useRef(0);
  const current = () => mounted.current && generation === storageGeneration();

  useEffect(() => {
    mounted.current = true;
    const requests = previewRequest, objectUrl = previewUrl;
    return () => { mounted.current = false; requests.current++; if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); };
  }, []);
  useEffect(() => {
    let active = true;
    void voiceService.getDefault().then(value => {
      if (active && generation === storageGeneration() && !chosenNarrator.current) {
        setVoiceId(value.voice_profile_id ? String(value.voice_profile_id) : "");
        if (value.voice_profile_id && !providerChanged.current) { setProviderId("qwen3_clone"); setExecution("server"); }
      }
    }).catch(() => {
      if (active && generation === storageGeneration() && !chosenNarrator.current) {
        const localVoice = accountStorage.getItem("nexus-reader-narrator-id") || ""; setVoiceId(localVoice);
        if (localVoice && !providerChanged.current) { setProviderId("qwen3_clone"); setExecution("server"); }
      }
    });
    return () => { active = false; };
  }, [generation]);
  useEffect(() => {
    let active = true, loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const [chaptersResult, voicesResult] = await Promise.allSettled([audioService.story(novelId, page * PAGE_SIZE, PAGE_SIZE), voiceService.list()]);
        if (active && generation === storageGeneration()) {
          if (chaptersResult.status === "fulfilled") {
            for(const row of chaptersResult.value.chapters){const identity=chapterIdentity(row);if(identity){observeChapterIdentity(novelId,identity,generation);chapterBindings.current.set(row.chapter_number,{identity,sourceVersion:row.source_version});}}
            setOverview(chaptersResult.value); setLoadError("");
          }
          else setLoadError("Couldn’t refresh chapter audio. Check your connection and try again.");
          if (voicesResult.status === "fulfilled") { setVoices(voicesResult.value); setVoiceError(""); }
          else setVoiceError("Couldn’t load narrator voices. Existing chapter audio remains available; try again shortly.");
        }
      } catch { if (active && generation === storageGeneration()) setLoadError("Couldn’t refresh chapter audio. Check your connection and try again."); }
      finally { loading = false; }
    };
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [novelId, page, generation, refresh]);
  useEffect(() => { const audio = audioRef.current; return () => audio?.pause(); }, [preview]);
  useEffect(() => {
    if (overview) void browserAudioQueue.hydrate(novelId, libraryId, overview.chapters.map(chapter => chapter.chapter_number)).catch(() => undefined);
  }, [overview, novelId, libraryId]);

  const readyVoices = voices.filter(voice => voice.status === "completed");
  const selectedVoice = readyVoices.find(voice => String(voice.id) === voiceId);
  const toggle = (number: number, checked: boolean) => {
    setError("");
    if (checked && selected.length >= 200) { setError("Select at most 200 chapters at a time."); return; }
    if(checked){const value=chapterBindings.current.get(number);if(!value){setError("Reload this chapter to verify its identity before selecting it.");return;}selectedBindings.current.set(number,{identity:{...value.identity},sourceVersion:value.sourceVersion});}
    else selectedBindings.current.delete(number);
    setSelected(rows => checked ? [...new Set([...rows, number])].sort((a, b) => a - b) : rows.filter(row => row !== number));
  };
  const addRange = async () => {
    const start=Number(rangeStart),end=Number(rangeEnd);
    if(!rangeStart.trim() || !rangeEnd.trim() || !Number.isInteger(start) || !Number.isInteger(end) || start< -2147483648 || end>2147483647 || end<start){setError("Choose actual chapter numbers, from the earlier chapter through the later chapter.");return;}
    setBusy(true);setError("");
    try{
      const page=await audioService.story(novelId,0,200,{from_chapter:start,to_chapter:end});
      if(!current())return;
      if(page.total>200)throw new AudioSelectionError("This range contains more than 200 chapters. Choose a smaller range.");
      const rows=page.chapters.filter(row=>row.chapter_number>=start && row.chapter_number<=end);
      const next=[...new Set([...selected,...rows.map(row=>row.chapter_number)])].sort((a,b)=>a-b);
      if(next.length>200)throw new AudioSelectionError("Select at most 200 chapters at a time.");
      for(const row of rows){const identity=chapterIdentity(row);if(!identity)throw new AudioSelectionError("Reload the chapter list to verify its identities.");observeChapterIdentity(novelId,identity,generation);chapterBindings.current.set(row.chapter_number,{identity,sourceVersion:row.source_version});}
      for(const row of rows)if(!selected.includes(row.chapter_number)){const value=chapterBindings.current.get(row.chapter_number);if(value)selectedBindings.current.set(row.chapter_number,{identity:{...value.identity},sourceVersion:value.sourceVersion});}
      setSelected(next);
    }catch(error){if(current())setError(error instanceof AudioSelectionError || error instanceof ChapterManifestChangedError ? error.message : getUserFacingError(error,"Couldn’t review this chapter range."));}
    finally{if(current())setBusy(false);}
  };

  const cloning = providerId === "qwen3_clone";
  const browserMode = !cloning && execution === "browser";
  const validProvider = cloning ? Boolean(selectedVoice) : Boolean(providerConfig.baseUrl.trim() && providerConfig.model.trim() && providerConfig.voice.trim() && (browserMode || !providerConfig.apiKey));
  const serverProvider = () => ({ id: providerId, base_url: providerConfig.baseUrl, model: providerConfig.model, voice: providerConfig.voice, language_code: providerConfig.languageCode, execution_mode: "server" as const });
  const rememberPlayback = () => {
    if (cloning && selectedVoice) accountStorage.setItem("nexus-reader-narrator-id", String(selectedVoice.id));
    accountStorage.setItem("nexus-reader-tts-engine", "openai_compatible");
    accountStorage.setItem("nexus-reader-tts-preset", providerId);
    accountStorage.setItem("nexus-reader-tts-execution", cloning ? "server" : execution);
    if (!cloning) {
      accountStorage.setItem("nexus-reader-tts-url", providerConfig.baseUrl);
      accountStorage.setItem("nexus-reader-tts-model", providerConfig.model);
      accountStorage.setItem("nexus-reader-tts-provider-voice", providerConfig.voice);
      accountStorage.setItem("nexus-reader-tts-language", providerConfig.languageCode || "");
    }
  };
  const chooseProvider = (id: ProviderId) => {
    providerChanged.current = true; setProviderId(id); setDiagnostic("");
    if (id === "qwen3_clone") { setExecution("server"); return; }
    const preset = TTS_PROVIDER_PRESETS.find(value => value.id === id)!;
    setProviderConfig(config => ({ ...preset.config, baseUrl: presetUrl(id, execution), apiKey: id === "custom" ? config.apiKey : "" }));
  };
  const changeExecution = (mode: "browser" | "server") => {
    providerChanged.current = true; setExecution(mode); setDiagnostic("");
    if (providerId !== "custom" && providerConfig.baseUrl === presetUrl(providerId, execution)) setProviderConfig(config => ({ ...config, baseUrl: presetUrl(providerId, mode) }));
  };
  const browserInput = (numbers: number[], selectedInput=false) => ({ novelId, libraryId, chapterNumbers: numbers, chapterIdentities:Object.fromEntries(numbers.map(number=>[number,(selectedInput?selectedBindings:chapterBindings).current.get(number)?.identity as ChapterIdentity])), sourceVersions:Object.fromEntries(numbers.map(number=>[number,(selectedInput?selectedBindings:chapterBindings).current.get(number)?.sourceVersion ?? ""])), provider: providerConfig, includeAuthorNotes: includeNotes, pronunciation: pronunciation ?? {version:null,rules:[]}, presetId: providerId as TtsProviderPresetId });
  const create = async () => {
    if (busy || !validProvider || !selected.length || !pronunciation) return;
    setBusy(true); setError(""); setResults(null);
    try {
      const identities=selected.map(chapter_number=>{const value=selectedBindings.current.get(chapter_number);if(!value)throw new AudioSelectionError("Reload the selected chapters to verify their identities.");assertCurrentChapterIdentity(novelId,value.identity);return {chapter_number,...expectedChapterIdentity(value.identity,value.sourceVersion ?? undefined)};});
      let result: StoryAudioBatch;
      if (browserMode) {
        browserAudioQueue.enqueue(browserInput(selected,true));
        result = { novel_id: novelId, outcomes: selected.map(chapter_number => ({ chapter_number, outcome: "queued", job: null })) };
      } else result = await audioService.createStory(novelId, { chapter_numbers: selected, chapter_identities:identities, include_author_notes: includeNotes,
        ...(cloning && selectedVoice ? { voice_profile_id: selectedVoice.id } : { provider: serverProvider() }) });
      if (current()) {
        rememberPlayback();
        setResults(result); setSelected([]);selectedBindings.current.clear(); setRefresh(value => value + 1);
      }
    } catch(error) { if (current()) setError(error instanceof AudioSelectionError || error instanceof ChapterManifestChangedError ? error.message : getUserFacingError(error,"Couldn’t queue these chapters. Your selection is preserved; check the narrator and try again.")); }
    finally { if (current()) setBusy(false); }
  };
  const changeJob = async (job: ServerAudioJob, cancel: boolean) => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      if (cancel) await audioService.cancel(job.id); else await audioService.retry(job.id);
      if (current()) setRefresh(value => value + 1);
    } catch { if (current()) setError(cancel ? "Couldn’t cancel this job. Try again." : "Couldn’t retry this job. Try again."); }
    finally { if (current()) setBusy(false); }
  };
  const play = async (job: ServerAudioJob, chapter: number) => {
    audioRef.current?.pause(); previewRequest.current++;
    const request = previewRequest.current;
    setError("");
    try {
      const blob = await audioService.audio(job.id);
      if (!current() || request !== previewRequest.current) return;
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
      const src = URL.createObjectURL(blob); previewUrl.current = src; setPreview({ src, chapter });
    } catch { if (current() && request === previewRequest.current) setError("Couldn’t load this chapter’s audio. Connect to Nexus and try again."); }
  };

  const localAction = (chapter: number, retry: boolean) => {
    setError("");
    try {
      if (retry) {
        if (!browserMode || !validProvider || !pronunciation) { setError("Choose this browser, its provider and saved pronunciations to retry local audio."); return; }
        browserAudioQueue.retry(browserInput([chapter])); rememberPlayback();
      } else browserAudioQueue.cancel(novelId, chapter);
    } catch { setError("Couldn’t update the browser audio job. Check the provider and try again."); }
  };
  const playLocal = async (chapter: number, identity?:ChapterIdentity) => {
    audioRef.current?.pause(); const request = ++previewRequest.current;
    try {
      const recording = await chapterAudioStore.recording(novelId, chapter);
      if (!current() || request !== previewRequest.current) return;
      const local = browserRows.find(row => row.chapterNumber === chapter && row.chapterIdentity?.chapter_key === identity?.chapter_key);
      if (!recording) { setError("This device no longer has that audio. Generate it again or use a server recording."); return; }
      if (!identity || !local?.sourceVersion || !recording.manifest || recording.manifest.job_id !== undefined || recording.manifest.source_version !== local.sourceVersion
          || !chapterIdentity(recording.manifest) || chapterIdentity(recording.manifest)!.chapter_key !== identity.chapter_key || chapterIdentity(recording.manifest)!.manifest_epoch !== identity.manifest_epoch) {
        setError("This device’s saved audio has changed. Use the matching server recording or refresh the chapter’s browser audio.");
        setRefresh(value => value + 1); return;
      }
      const blob = recording.audio;
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
      const src = URL.createObjectURL(blob); previewUrl.current = src; setPreview({ src, chapter });
    } catch { if (current() && request === previewRequest.current) setError("Couldn’t open this device’s audio."); }
  };
  const diagnose = async (voicePreview: boolean) => {
    if (!validProvider || cloning || busy) return;
    setBusy(true); setDiagnostic("");
    const request = ++previewRequest.current;
    try {
      if (browserMode) {
        if (!voicePreview) { setDiagnostic("Browser providers are checked when you explicitly preview or create audio."); return; }
        const blob = await ttsService.synthesize("Nexus is ready to read this story aloud.", providerConfig);
        if (!current() || request !== previewRequest.current) return;
        audioRef.current?.pause();
        if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
        const src = URL.createObjectURL(blob); previewUrl.current = src; setPreview({ src, chapter: 0 });
      } else {
        const result = voicePreview ? await audioService.preview(serverProvider()) : await audioService.check(serverProvider());
        if (current() && request === previewRequest.current) setDiagnostic(voicePreview ? `Preview succeeded (${result.bytes} bytes of valid audio).` : "Provider is reachable from the Nexus server.");
      }
    } catch { if (current() && request === previewRequest.current) setDiagnostic("The provider could not be reached or returned invalid audio. Check its settings and try again."); }
    finally { if (current()) setBusy(false); }
  };
  const removeLocal = async () => {
    if (removeChapter === null || busy) return;
    setBusy(true); setError("");
    const chapter = removeChapter;
    if (preview?.chapter === chapter) {
      previewRequest.current++; audioRef.current?.pause();
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
      previewUrl.current = null; setPreview(null);
    }
    try {
      await browserAudioQueue.remove(novelId, chapter);
      if (current()) { setRemoveChapter(null); setRefresh(value => value + 1); }
    } catch { if (current()) setError("Couldn’t remove this device’s recording. Cancel any active preparation and try again."); }
    finally { if (current()) setBusy(false); }
  };
  const localControls = (row: BrowserAudioRow) => <>
    {row.status === "ready" && <Button onClick={() => void playLocal(row.chapterNumber,row.chapterIdentity)}>Listen to local chapter {row.chapterNumber}</Button>}
    {["queued", "generating"].includes(row.status) && <Button onClick={() => localAction(row.chapterNumber, false)}>Cancel local chapter {row.chapterNumber}</Button>}
    {["failed", "cancelled"].includes(row.status) && <Button disabled={busy} onClick={() => localAction(row.chapterNumber, true)}>Retry local chapter {row.chapterNumber}</Button>}
    {!["queued", "generating"].includes(row.status) && <Button variant="danger" disabled={busy} onClick={() => setRemoveChapter(row.chapterNumber)}>Remove local chapter {row.chapterNumber}</Button>}
  </>;

  return <section className="story-audio" aria-label="Story audio">
    <h2>Audio</h2>
    <p>Choose a voice provider and chapters to prepare audio. Nexus server jobs continue after you leave; browser jobs continue while this app stays open.</p>
    <p><Link to="/settings/voices">Manage narrator voices in Settings</Link></p>
    {error && <Banner tone="warning">{error}</Banner>}
    {loadError && <Banner tone="warning">{loadError}</Banner>}
    {voiceError && <Banner tone="warning">{voiceError}</Banner>}
    {overview && <p role="status">{overview.summary.ready} chapters ready to listen · {overview.summary.queued} queued or preparing · {overview.summary.needs_retry} need attention · {overview.summary.downloaded} of {overview.summary.chapters} chapters downloaded</p>}
    <Select label="Voice provider" value={providerId} disabled={busy} onChange={event => chooseProvider(event.target.value as ProviderId)} options={[{ value: "qwen3_clone", label: "My cloned narrator · local Qwen3" }, ...TTS_PROVIDER_PRESETS.map(preset => ({ value: preset.id, label: preset.label }))]} />
    {cloning ? <><Select label="Narrator" value={selectedVoice ? voiceId : ""} disabled={busy} onChange={event => {
      chosenNarrator.current = true; setVoiceId(event.target.value);
    }} options={[{ value: "", label: "Choose a ready narrator" }, ...readyVoices.map(voice => ({ value: String(voice.id), label: `${voice.name} · ${voice.language}` }))]} />
    {!readyVoices.length && <p>No narrator is ready yet. Upload a recording in Settings, then return here when its preview is ready.</p>}</> : <fieldset className="story-audio__provider" disabled={busy}>
      <legend>Provider settings</legend>
      <p>{TTS_PROVIDER_PRESETS.find(preset => preset.id === providerId)?.description}</p>
      <Select label="Generate audio" value={execution} onChange={event => changeExecution(event.target.value as "browser" | "server")} options={[{ value: "browser", label: "In this browser" }, { value: "server", label: "On the Nexus server" }]} />
      <Input label="API base URL" type="url" value={providerConfig.baseUrl} onChange={event => setProviderConfig(config => ({ ...config, baseUrl: event.target.value }))} hint={browserMode ? "localhost refers to this device. The provider must allow browser access." : "This address is reached by the Nexus server. host.docker.internal reaches this Mac from its containers; custom URLs stay as entered."} />
      <Input label="Model" value={providerConfig.model} onChange={event => setProviderConfig(config => ({ ...config, model: event.target.value }))} />
      <Input label="Voice" value={providerConfig.voice} onChange={event => setProviderConfig(config => ({ ...config, voice: event.target.value }))} />
      <Input label="Language code" value={providerConfig.languageCode || ""} onChange={event => setProviderConfig(config => ({ ...config, languageCode: event.target.value }))} />
      <Input label="API key" type="password" autoComplete="off" value={providerConfig.apiKey} onChange={event => setProviderConfig(config => ({ ...config, apiKey: event.target.value }))} hint="Used only by this browser. It is never sent to Nexus or stored with jobs." />
      {!browserMode && providerConfig.apiKey && <p role="status">This key can only be used in this browser. Switch to browser generation, or clear it to use a keyless server endpoint.</p>}
      <div className="story-audio__actions"><Button disabled={!validProvider} onClick={() => void diagnose(false)}>Check provider</Button><Button disabled={!validProvider} onClick={() => void diagnose(true)}>Preview voice</Button></div>
      {diagnostic && <p role="status">{diagnostic}</p>}
    </fieldset>}
    <PronunciationEditor novelId={novelId} onReady={setPronunciation} />
    {!pronunciation && <p role="status">New audio is waiting for pronunciation settings. Open Pronunciation to load or save them.</p>}
    <Checkbox label="Include author notes in new audio" checked={includeNotes} disabled={busy} onChange={event => setIncludeNotes(event.target.checked)} />
    <fieldset className="story-audio__range" disabled={busy}>
      <legend>Select chapters</legend>
      <Input label="From chapter" type="number" min={-2147483648} max={2147483647} value={rangeStart} onChange={event => setRangeStart(event.target.value)} />
      <Input label="Through chapter" type="number" min={-2147483648} max={2147483647} value={rangeEnd} onChange={event => setRangeEnd(event.target.value)} />
      <Button onClick={()=>void addRange()}>Add chapter range</Button>
      <Button disabled={!selected.length} onClick={() => { setSelected([]);selectedBindings.current.clear(); setResults(null); }}>Clear selection</Button>
    </fieldset>
    <p aria-live="polite">{selected.length ? `${selected.length} chapters selected: ${selected.join(", ")}` : "No chapters selected."}</p>
    <p>Only downloaded chapters can be narrated. Existing matching audio is kept; failed jobs require an explicit retry. A batch contains at most 200 chapters.</p>
    <Button variant="primary" disabled={busy || !selected.length || !validProvider || !pronunciation} onClick={() => void create()}>{busy ? "Working…" : "Create selected audio"}</Button>
    {results && <section aria-label="Audio creation results"><h3>Chapter outcomes</h3><ul>{results.outcomes.map(row => <li key={row.chapter_number}>Chapter {row.chapter_number}: {row.message || outcomeLabels[row.outcome]}</li>)}</ul></section>}
    {preview && <div><p>{preview.chapter ? `Listening to chapter ${preview.chapter}` : "Voice preview"}</p><audio ref={audioRef} controls autoPlay src={preview.src} aria-label={preview.chapter ? `Chapter ${preview.chapter} audio` : "Voice preview"} /></div>}
    {browserRows.length > 0 && <section aria-label="This device’s audio queue">
      <p role="status">This device: {browserRows.filter(row => ["queued", "generating"].includes(row.status)).length} queued or preparing · {browserRows.filter(row => row.status === "ready").length} ready · {browserRows.filter(row => row.status === "failed").length} need attention</p>
      {browserRows.some(row => ["queued", "generating"].includes(row.status)) && <Button onClick={() => browserAudioQueue.cancel(novelId)}>Cancel this device’s queue</Button>}
      {browserRows.filter(row => !overview?.chapters.some(chapter => chapter.chapter_number === row.chapterNumber)).map(row => <div key={row.chapterNumber}><p>Chapter {row.chapterNumber}: {row.status} · {row.completedParts} of {row.totalParts} parts{row.error ? ` · ${row.error}` : ""}</p>{localControls(row)}</div>)}
    </section>}
    <Dialog open={removeChapter !== null} onClose={() => { if (!busy) setRemoveChapter(null); }} title={`Remove this device’s chapter ${removeChapter} audio?`} description="This removes the browser recording and its completed preparation parts. Downloaded text and server recordings are kept. You can then create audio with another voice or provider." actions={<><Button disabled={busy} onClick={() => setRemoveChapter(null)}>Keep recording</Button><Button variant="danger" loading={busy} onClick={() => void removeLocal()}>Remove recording</Button></>} />
    {!overview && <p role="status">Loading chapters…</p>}
    {overview && <>
      <ul className="story-audio-chapters">{overview.chapters.map(chapter => {
        const job = chapter.latest_job;
        const local = browserRows.find(row => row.chapterNumber === chapter.chapter_number && row.chapterIdentity?.chapter_key === chapterIdentity(chapter)?.chapter_key);
        const outdated = Boolean(job?.source_version && chapter.source_version && job.source_version !== chapter.source_version);
        return <li key={chapter.id}>
          <Checkbox label={`Chapter ${chapter.chapter_number}: ${chapter.title || "Untitled chapter"}`} checked={selected.includes(chapter.chapter_number)} disabled={busy || !chapter.downloaded} onChange={event => toggle(chapter.chapter_number, event.target.checked)} />
          {local && <div><p>On this device: {local.status} · {local.completedParts} of {local.totalParts} parts</p>{local.error && <p>{local.error}</p>}{local.sourceVersion && chapter.source_version && local.sourceVersion !== chapter.source_version && <p>This device’s recording uses an earlier chapter version. Passage links are unavailable.</p>}{["queued", "generating"].includes(local.status) && <progress value={local.completedParts} max={Math.max(1, local.totalParts)} aria-label={`Chapter ${chapter.chapter_number} browser audio preparation`} />}<div className="story-audio__actions">{localControls(local)}</div></div>}
          <p>{chapter.downloaded ? "Text downloaded" : "Text not downloaded — download it from Chapters first"}{job ? ` · ${job.audio_ready ? "Audio ready" : job.status === "processing" ? "Preparing" : job.status === "retry_wait" ? "Waiting to retry" : job.status}` : " · No audio yet"}{job ? ` · ${job.completed_parts} of ${job.total_parts} parts` : ""}</p>
          {job && <p>Narrator: {job.provider_voice}</p>}
          {job && activeJob(job) && <progress value={job.completed_parts} max={Math.max(1, job.total_parts)} aria-label={`Chapter ${chapter.chapter_number} audio preparation`} />}
          {job?.error && <p>{job.error}</p>}
          {outdated && <p>This recording uses an earlier chapter version. You can listen, but passage links are unavailable.</p>}
          <div className="story-audio__actions">
            <Link to={`/library/${libraryId}/novels/${novelId}/${chapter.chapter_number}`}>Open chapter {chapter.chapter_number}</Link>
            {job?.audio_ready && <Button onClick={() => void play(job, chapter.chapter_number)}>Listen to chapter {chapter.chapter_number}</Button>}
            {job && ["failed", "cancelled"].includes(job.status) && <Button disabled={busy} onClick={() => void changeJob(job, false)}>Retry chapter {chapter.chapter_number}</Button>}
            {job && activeJob(job) && <Button disabled={busy} onClick={() => void changeJob(job, true)}>Cancel chapter {chapter.chapter_number}</Button>}
          </div>
        </li>;
      })}</ul>
      <nav className="story-audio__actions" aria-label="Audio chapter pages">
        <Button disabled={busy || page === 0} onClick={() => setPage(value => value - 1)}>Previous chapters</Button>
        <span> {overview.total ? overview.offset + 1 : 0}–{Math.min(overview.offset + overview.chapters.length, overview.total)} of {overview.total} </span>
        <Button disabled={busy || (page + 1) * PAGE_SIZE >= overview.total} onClick={() => setPage(value => value + 1)}>Next chapters</Button>
      </nav>
    </>}
    <details onToggle={event=>setShowSaved(event.currentTarget.open)}>
      <summary>Saved recordings and preserved originals</summary>
      {showSaved&&<StorySavedRecordings novelId={novelId}/>}
    </details>
    <details onToggle={event => setShowExports(event.currentTarget.open)}>
      <summary>Audiobook exports and private podcast</summary>
      {showExports && <StoryAudioExports novelId={novelId} libraryId={libraryId} selectedChapterNumbers={selected} />}
    </details>
  </section>;
}

export default function StoryAudio(props: { novelId: number; libraryId: number }) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <StoryAudioContents key={`${generation}:${props.novelId}:${props.libraryId}`} {...props} />;
}
