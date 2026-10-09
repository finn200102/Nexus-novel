import React, { useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw, Settings2, SkipBack, SkipForward, Square, Trash2, WandSparkles, X } from "lucide-react";
import { Button, IconButton, Input, Select, Sheet } from "../ui";
import { ChapterAudioJob, chapterAudioJobStore, chapterAudioStore } from "../../services/offlineReaderStore";
import { mergeAudioSegments, OpenAICompatibleTtsConfig, splitTextForSynthesis, TtsProviderPresetId, TTS_PROVIDER_PRESETS, TtsRequestError, ttsService } from "../../services/ttsService";
import { audioService, ServerAudioJob } from "../../services/audioService";

export interface ListenChapter {
  id: number;
  chapter_number: number;
  title: string;
  content: string;
}

interface ListenPlayerProps {
  chapter: ListenChapter;
  libraryId: number;
  novelId: number;
  /** The player is docked and visible. Closing it stops narration. */
  open: boolean;
  onClose: () => void;
  onPlayingChange?: (playing: boolean) => void;
}

const RATES = [0.8, 1, 1.2, 1.4, 1.6];

const formatAudioTime = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const wholeSeconds = Math.floor(seconds);
  return `${Math.floor(wholeSeconds / 60)}:${String(wholeSeconds % 60).padStart(2, "0")}`;
};

/**
 * Listen (TTS) mini player docked above the reader's bottom bar, plus a "Listen settings"
 * sheet for the provider. Browser voices speak directly; self-hosted / API providers
 * generate chapter audio in this browser (local-only) or as a durable Nexus server job.
 */
const ListenPlayer: React.FC<ListenPlayerProps> = ({ chapter, libraryId: library_id, novelId: novel_id, open, onClose, onPlayingChange }) => {
  const chapter_number = chapter.chapter_number;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [ttsAvailable] = useState(() => typeof window !== "undefined" && "speechSynthesis" in window);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceName, setVoiceName] = useState(() => localStorage.getItem("nexus-reader-tts-voice") || "");
  const [ttsRate, setTtsRate] = useState(() => Number(localStorage.getItem("nexus-reader-tts-rate")) || 1);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [ttsEngine, setTtsEngine] = useState<"native" | "openai_compatible">(() => (localStorage.getItem("nexus-reader-tts-engine") as "native" | "openai_compatible") || "native");
  const [ttsPreset, setTtsPreset] = useState<TtsProviderPresetId>(() => (localStorage.getItem("nexus-reader-tts-preset") as TtsProviderPresetId) || "kokoro_mps");
  const [providerConfig, setProviderConfig] = useState<OpenAICompatibleTtsConfig>(() => ({
    baseUrl: localStorage.getItem("nexus-reader-tts-url") || "http://localhost:8880/v1",
    apiKey: localStorage.getItem("nexus-reader-tts-key") || "",
    model: localStorage.getItem("nexus-reader-tts-model") || "kokoro",
    voice: localStorage.getItem("nexus-reader-tts-provider-voice") || "af_bella",
    languageCode: localStorage.getItem("nexus-reader-tts-language") || undefined,
  }));
  const [ttsExecutionMode, setTtsExecutionMode] = useState<"browser" | "server">(() => (localStorage.getItem("nexus-reader-tts-execution") as "browser" | "server") || "browser");
  const [chapterAudioReady, setChapterAudioReady] = useState(false);
  const [audioJob, setAudioJob] = useState<ChapterAudioJob | null>(null);
  const [serverAudioJob, setServerAudioJob] = useState<ServerAudioJob | null>(null);
  const [audioPlayerError, setAudioPlayerError] = useState<string | null>(null);
  const [audioCurrentTime, setAudioCurrentTime] = useState(0);
  const [audioDuration, setAudioDuration] = useState(0);
  const [sleepMinutes, setSleepMinutes] = useState(() => Number(localStorage.getItem("nexus-reader-audio-sleep-minutes")) || 0);
  const [providerDiagnostic, setProviderDiagnostic] = useState<string | null>(null);
  const providerAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioControllerRef = useRef<AbortController | null>(null);
  const audioObjectUrlRef = useRef<string | null>(null);
  const audioJobRunningRef = useRef(false);
  const sleepTimerRef = useRef<number | null>(null);

  useEffect(() => { onPlayingChange?.(isSpeaking); }, [isSpeaking, onPlayingChange]);

  // Saved audio and local generation jobs for this chapter.
  useEffect(() => {
    let active = true;
    void Promise.all([
      chapterAudioStore.get(novel_id, chapter_number),
      chapterAudioJobStore.get(novel_id, chapter_number),
    ]).then(([audio, job]) => {
      if (!active) return;
      setChapterAudioReady(Boolean(audio));
      setAudioJob(job);
      setAudioCurrentTime(Number(localStorage.getItem(`nexus-reader-audio-position-${novel_id}-${chapter_number}`)) || 0);
      setAudioPlayerError(null);
    }).catch(() => {
      if (!active) return;
      setChapterAudioReady(false);
      setAudioJob(null);
    });
    return () => { active = false; };
  }, [novel_id, chapter_number]);

  useEffect(() => { localStorage.setItem("nexus-reader-tts-voice", voiceName); }, [voiceName]);

  useEffect(() => {
    localStorage.setItem("nexus-reader-tts-rate", String(ttsRate));
    if (providerAudioRef.current) providerAudioRef.current.playbackRate = ttsRate;
  }, [ttsRate]);

  useEffect(() => {
    localStorage.setItem("nexus-reader-tts-engine", ttsEngine);
    localStorage.setItem("nexus-reader-tts-preset", ttsPreset);
    localStorage.setItem("nexus-reader-tts-url", providerConfig.baseUrl);
    localStorage.setItem("nexus-reader-tts-key", providerConfig.apiKey);
    localStorage.setItem("nexus-reader-tts-model", providerConfig.model);
    localStorage.setItem("nexus-reader-tts-provider-voice", providerConfig.voice);
    localStorage.setItem("nexus-reader-tts-execution", ttsExecutionMode);
    if (providerConfig.languageCode) localStorage.setItem("nexus-reader-tts-language", providerConfig.languageCode);
    else localStorage.removeItem("nexus-reader-tts-language");
  }, [providerConfig, ttsEngine, ttsPreset, ttsExecutionMode]);

  useEffect(() => {
    localStorage.setItem("nexus-reader-audio-sleep-minutes", String(sleepMinutes));
    if (sleepTimerRef.current) window.clearTimeout(sleepTimerRef.current);
    sleepTimerRef.current = null;
    if (!sleepMinutes || !isSpeaking) return;
    sleepTimerRef.current = window.setTimeout(() => {
      providerAudioRef.current?.pause();
      if (ttsAvailable) window.speechSynthesis.cancel();
      setIsSpeaking(false);
      setProviderDiagnostic("Sleep timer paused chapter audio.");
    }, sleepMinutes * 60_000);
    return () => {
      if (sleepTimerRef.current) window.clearTimeout(sleepTimerRef.current);
      sleepTimerRef.current = null;
    };
  }, [sleepMinutes, isSpeaking, ttsAvailable]);

  useEffect(() => {
    if (!ttsAvailable) return;
    const refreshVoices = () => setVoices(window.speechSynthesis.getVoices());
    refreshVoices();
    window.speechSynthesis.addEventListener("voiceschanged", refreshVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", refreshVoices);
  }, [ttsAvailable]);

  useEffect(() => {
    // Never allow narration from the previous chapter to continue after
    // navigation or when the reader unmounts.
    return () => {
      if (ttsAvailable) window.speechSynthesis.cancel();
      audioControllerRef.current?.abort();
      providerAudioRef.current?.pause();
      if (sleepTimerRef.current) window.clearTimeout(sleepTimerRef.current);
      if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
      providerAudioRef.current = null;
      audioObjectUrlRef.current = null;
      setIsSpeaking(false);
    };
  }, [chapter.id, ttsAvailable]);

  const chapterId = chapter.id;
  useEffect(() => {
    let active = true;
    audioService.list(chapterId).then((jobs) => {
      if (active) setServerAudioJob(jobs[0] || null);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [chapterId]);

  const serverAudioJobId = serverAudioJob?.id;
  const serverAudioJobStatus = serverAudioJob?.status;
  useEffect(() => {
    if (serverAudioJobId === undefined || !["queued", "processing", "retry_wait"].includes(serverAudioJobStatus ?? "")) return;
    const timer = window.setInterval(() => {
      audioService.get(serverAudioJobId).then((job) => {
        setServerAudioJob(job);
        if (job.audio_ready) setChapterAudioReady(true);
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [serverAudioJobId, serverAudioJobStatus]);

  const stopTts = () => {
    if (ttsAvailable) window.speechSynthesis.cancel();
    providerAudioRef.current?.pause();
    setIsSpeaking(false);
  };

  const close = () => { stopTts(); setSettingsOpen(false); onClose(); };

  const audioPositionKey = () => `nexus-reader-audio-position-${novel_id}-${chapter_number}`;

  const saveAudioJob = async (job: ChapterAudioJob) => {
    await chapterAudioJobStore.save(job);
    setAudioJob({ ...job, updated_at: Date.now() });
  };

  const generateServerAudio = async () => {
    try {
      if (serverAudioJob && ["failed", "cancelled", "retry_wait"].includes(serverAudioJob.status)) {
        setServerAudioJob(await audioService.retry(serverAudioJob.id));
        setAudioPlayerError(null);
        return;
      }
      const job = await audioService.create({
        library_id,
        novel_id,
        chapter_number: chapter.chapter_number,
        provider: {
          id: ttsPreset,
          base_url: providerConfig.baseUrl,
          model: providerConfig.model,
          voice: providerConfig.voice,
          language_code: providerConfig.languageCode,
          execution_mode: "server",
        },
      });
      setServerAudioJob(job);
      setAudioPlayerError(null);
    } catch (error) {
      setAudioPlayerError(error instanceof Error ? error.message : "Could not start the server audio job.");
    }
  };

  const generateChapterAudio = async () => {
    if (audioJob?.status === "generating" || audioJobRunningRef.current) return;
    if (ttsExecutionMode === "server") {
      await generateServerAudio();
      return;
    }
    audioJobRunningRef.current = true;
    const controller = new AbortController();
    audioControllerRef.current = controller;
    setAudioPlayerError(null);
    let job: ChapterAudioJob | null = null;
    try {
      const existing = await chapterAudioJobStore.get(novel_id, chapter.chapter_number);
      const activeProvider = existing?.provider || {
        base_url: providerConfig.baseUrl,
        model: providerConfig.model,
        voice: providerConfig.voice,
        language_code: providerConfig.languageCode,
      };
      const completedChunks = existing?.status === "failed" || existing?.status === "cancelled" || existing?.status === "queued"
        ? existing.completed_chunks : 0;
      const isSparkProvider = activeProvider.model.includes("Spark-TTS");
      // Spark-TTS is happiest with short passages.  Preserve completed parts,
      // but re-chunk only the pending long passages on resume so a recoverable
      // job becomes more reliable without discarding any local audio.
      const chunks = existing?.chunks?.length
        ? (isSparkProvider
          ? [
              ...existing.chunks.slice(0, completedChunks),
              ...existing.chunks.slice(completedChunks).flatMap((chunk) => splitTextForSynthesis(chunk, 380)),
            ]
          : existing.chunks)
        : splitTextForSynthesis(`${chapter.title}. ${chapter.content}`, isSparkProvider ? 380 : 1_100);
      if (!chunks.length) {
        setAudioPlayerError("This chapter has no text to turn into audio.");
        return;
      }
      job = {
        cache_key: `${novel_id}:${chapter.chapter_number}`,
        novel_id,
        chapter_number: chapter.chapter_number,
        chunks,
        completed_chunks: completedChunks,
        provider: activeProvider,
        status: "generating",
        created_at: existing?.created_at || Date.now(),
        updated_at: Date.now(),
      };
      await saveAudioJob(job);
      for (let index = job.completed_chunks; index < job.chunks.length; index += 1) {
        const audio = await ttsService.synthesize(job.chunks[index], {
          ...providerConfig,
          baseUrl: job.provider?.base_url || providerConfig.baseUrl,
          model: job.provider?.model || providerConfig.model,
          voice: job.provider?.voice || providerConfig.voice,
          languageCode: job.provider?.language_code || providerConfig.languageCode,
        }, controller.signal);
        await chapterAudioJobStore.saveSegment(novel_id, chapter.chapter_number, index, audio);
        job.completed_chunks = index + 1;
        await saveAudioJob(job);
      }
      const segments = await chapterAudioJobStore.segments(novel_id, chapter.chapter_number);
      await chapterAudioStore.save(novel_id, chapter.chapter_number, await mergeAudioSegments(segments));
      await chapterAudioJobStore.clearSegments(novel_id, chapter.chapter_number);
      job.status = "ready";
      job.error = undefined;
      await saveAudioJob(job);
      setChapterAudioReady(true);
    } catch (error) {
      if (!job) {
        setAudioPlayerError("Could not start the audio job. Please retry.");
        return;
      }
      if (error instanceof DOMException && error.name === "AbortError") {
        job.status = "cancelled";
        job.error = "Generation paused. You can resume from the last completed part.";
      } else {
        const providerError = error instanceof TtsRequestError ? error : null;
        job.status = "failed";
        job.error = providerError?.message || "Audio generation failed. Retry to continue from the last completed part.";
      }
      await saveAudioJob(job);
      setAudioPlayerError(job.error || "Audio generation failed.");
    } finally {
      if (audioControllerRef.current === controller) audioControllerRef.current = null;
      audioJobRunningRef.current = false;
    }
  };

  const cancelAudioGeneration = async () => {
    if (ttsExecutionMode === "server" && serverAudioJob && ["queued", "processing", "retry_wait"].includes(serverAudioJob.status)) {
      try { setServerAudioJob(await audioService.cancel(serverAudioJob.id)); }
      catch (error) { setAudioPlayerError(error instanceof Error ? error.message : "Could not pause the server audio job."); }
      return;
    }
    audioControllerRef.current?.abort();
  };

  const loadChapterAudioPlayer = async (): Promise<HTMLAudioElement | null> => {
    if (providerAudioRef.current) return providerAudioRef.current;
    const audioBlob = serverAudioJob?.audio_ready
      ? await audioService.audio(serverAudioJob.id)
      : await chapterAudioStore.get(novel_id, chapter.chapter_number);
    if (!audioBlob) {
      setChapterAudioReady(false);
      return null;
    }
    const audio = new Audio();
    const url = URL.createObjectURL(audioBlob);
    audioObjectUrlRef.current = url;
    audio.src = url;
    audio.preload = "metadata";
    audio.playbackRate = ttsRate;
    audio.onloadedmetadata = () => {
      setAudioDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
      const saved = Number(localStorage.getItem(audioPositionKey())) || 0;
      audio.currentTime = Math.min(saved, Number.isFinite(audio.duration) ? audio.duration : saved);
      setAudioCurrentTime(audio.currentTime);
    };
    audio.ontimeupdate = () => {
      setAudioCurrentTime(audio.currentTime);
      localStorage.setItem(audioPositionKey(), String(audio.currentTime));
    };
    audio.onended = () => {
      localStorage.setItem(audioPositionKey(), "0");
      setAudioCurrentTime(0);
      setIsSpeaking(false);
    };
    audio.onerror = () => {
      setAudioPlayerError("The saved chapter audio could not be played. Generate it again to repair it.");
      setIsSpeaking(false);
    };
    providerAudioRef.current = audio;
    return audio;
  };

  const playChapterAudio = async () => {
    const audio = await loadChapterAudioPlayer();
    if (!audio) return;
    if (isSpeaking) {
      audio.pause();
      setIsSpeaking(false);
      return;
    }
    try {
      audio.playbackRate = ttsRate;
      await audio.play();
      setIsSpeaking(true);
      setAudioPlayerError(null);
    } catch {
      setAudioPlayerError("Your browser could not start saved chapter audio.");
    }
  };

  const setChapterAudioPosition = async (position: number, relative = false) => {
    const audio = await loadChapterAudioPlayer();
    if (!audio) return;
    const duration = Number.isFinite(audio.duration) ? audio.duration : audioDuration;
    const target = relative ? audio.currentTime + position : position;
    audio.currentTime = Math.max(0, Math.min(duration || Number.MAX_SAFE_INTEGER, target));
    setAudioCurrentTime(audio.currentTime);
    localStorage.setItem(audioPositionKey(), String(audio.currentTime));
  };

  const deleteChapterAudio = async () => {
    stopTts();
    if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
    providerAudioRef.current = null;
    audioObjectUrlRef.current = null;
    if (ttsExecutionMode === "server" && serverAudioJob) {
      try {
        await audioService.remove(serverAudioJob.id);
        setServerAudioJob(null);
      } catch (error) {
        setAudioPlayerError(error instanceof Error ? error.message : "Could not delete the saved audio.");
        return;
      }
    } else {
      await chapterAudioStore.remove(novel_id, chapter.chapter_number);
      await chapterAudioJobStore.remove(novel_id, chapter.chapter_number);
    }
    setChapterAudioReady(false);
    setAudioJob(null);
    setAudioDuration(0);
    setAudioCurrentTime(0);
    localStorage.removeItem(audioPositionKey());
  };

  const diagnoseProvider = async (preview = false) => {
    if (ttsExecutionMode !== "server") {
      setProviderDiagnostic("Browser-local providers are checked by the browser when generation starts.");
      return;
    }
    if (providerConfig.apiKey) {
      setProviderDiagnostic("Server jobs do not store browser API keys. Use a self-hosted server URL without a browser-only key, or switch to This browser.");
      return;
    }
    try {
      const request = { id: ttsPreset, execution_mode: "server" as const, base_url: providerConfig.baseUrl, model: providerConfig.model, voice: providerConfig.voice, language_code: providerConfig.languageCode };
      const result = preview ? await audioService.preview(request) : await audioService.check(request);
      setProviderDiagnostic(preview ? `Preview succeeded (${result.bytes} bytes of valid WAV audio).` : "Provider is reachable from the Nexus server.");
    } catch (error) {
      setProviderDiagnostic(error instanceof Error ? error.message : "Provider check failed.");
    }
  };

  const applyTtsPreset = (presetId: TtsProviderPresetId) => {
    setTtsPreset(presetId);
    if (presetId === "custom") return;
    const preset = TTS_PROVIDER_PRESETS.find((item) => item.id === presetId);
    if (!preset) return;
    setTtsEngine("openai_compatible");
    setTtsExecutionMode("browser");
    setProviderConfig((current) => ({ ...preset.config, apiKey: current.apiKey }));
  };

  const toggleTts = () => {
    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
      stopTts();
      return;
    }
    if (providerAudioRef.current || isSpeaking) { stopTts(); return; }
    if (ttsEngine === "openai_compatible") { return; }
    if (!ttsAvailable) return;
    const utterance = new SpeechSynthesisUtterance(`${chapter.title}. ${chapter.content}`);
    const selectedVoice = voices.find((voice) => voice.name === voiceName);
    if (selectedVoice) utterance.voice = selectedVoice;
    utterance.rate = ttsRate;
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    setIsSpeaking(true);
    window.speechSynthesis.speak(utterance);
  };

  const server = ttsExecutionMode === "server";
  const jobStatus = server ? serverAudioJob?.status : audioJob?.status;
  const done = server ? serverAudioJob?.completed_parts || 0 : audioJob?.completed_chunks || 0;
  const total = server ? serverAudioJob?.total_parts || 0 : audioJob?.chunks.length || 0;
  const generating = server ? ["queued", "processing"].includes(jobStatus || "") : jobStatus === "generating";
  const pausable = server ? ["queued", "processing", "retry_wait"].includes(jobStatus || "") : jobStatus === "generating";
  const retryable = server ? ["failed", "cancelled", "retry_wait"].includes(jobStatus || "") : jobStatus === "failed" || jobStatus === "cancelled";
  const jobError = server ? serverAudioJob?.error : audioJob?.error;
  const statusLabel = server
    ? jobStatus === "processing" ? `Generating ${done}/${total} parts on Nexus`
      : jobStatus === "queued" ? "Queued on Nexus server"
      : jobStatus === "retry_wait" ? `Retry scheduled · ${done}/${total} parts saved`
      : jobStatus === "failed" ? `Failed at part ${done + 1}/${total}`
      : jobStatus === "cancelled" ? `Paused at ${done}/${total} parts`
      : chapterAudioReady ? "Ready to play" : "Not generated"
    : jobStatus === "generating" ? `Generating ${done}/${total} parts`
      : jobStatus === "queued" ? `Queued · ${done}/${total} parts saved`
      : jobStatus === "failed" ? `Failed at part ${done + 1}/${total}`
      : jobStatus === "cancelled" ? `Paused at ${done}/${total} parts`
      : chapterAudioReady ? "Ready to play" : "Not generated";
  const providerSummary = server && serverAudioJob
    ? `${serverAudioJob.provider_model} · ${serverAudioJob.provider_voice} · on Nexus`
    : audioJob?.provider ? `${audioJob.provider.model} · ${audioJob.provider.voice} · this browser` : null;
  const rateOptions = RATES.map((rate) => ({ value: String(rate), label: `${rate}×` }));
  const setProvider = (patch: Partial<OpenAICompatibleTtsConfig>, custom = true) => {
    if (custom) setTtsPreset("custom");
    setProviderConfig((current) => ({ ...current, ...patch }));
  };

  return (
    <>
      {open && (
        <section className="reader-listen" aria-label="Listen">
          {ttsEngine === "openai_compatible" ? (
            chapterAudioReady ? (
              <div className="reader-listen__row">
                <IconButton label="Back 15 seconds" icon={<SkipBack />} onClick={() => void setChapterAudioPosition(-15, true)} />
                <IconButton className="reader-listen__play" label={isSpeaking ? "Pause" : "Play"} icon={isSpeaking ? <Pause /> : <Play />} onClick={() => void playChapterAudio()} />
                <IconButton label="Forward 15 seconds" icon={<SkipForward />} onClick={() => void setChapterAudioPosition(15, true)} />
                <label className="reader-listen__scrubber">
                  <span className="visually-hidden">Position</span>
                  <span aria-hidden="true">{formatAudioTime(audioCurrentTime)}</span>
                  <input type="range" min="0" max={Math.max(audioDuration, 1)} step="1" value={Math.min(audioCurrentTime, Math.max(audioDuration, 1))} aria-valuetext={`${formatAudioTime(audioCurrentTime)} of ${formatAudioTime(audioDuration)}`} onChange={(event) => void setChapterAudioPosition(Number(event.target.value))} />
                  <span aria-hidden="true">{formatAudioTime(audioDuration)}</span>
                </label>
              </div>
            ) : (
              <div className="reader-listen__row">
                <Button variant="primary" size="sm" icon={<WandSparkles aria-hidden="true" />} loading={generating} disabled={generating} onClick={() => void generateChapterAudio()}>
                  {generating ? "Generating…" : done ? "Resume generation" : "Generate chapter audio"}
                </Button>
                {pausable && <Button size="sm" variant="ghost" icon={<Pause aria-hidden="true" />} onClick={() => void cancelAudioGeneration()}>Pause</Button>}
                {retryable && <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden="true" />} onClick={() => void generateChapterAudio()}>Retry</Button>}
                <span className="reader-listen__status" aria-live="polite">{statusLabel}{total ? ` · ${Math.round((done / Math.max(total, 1)) * 100)}%` : ""}</span>
              </div>
            )
          ) : ttsAvailable ? (
            <div className="reader-listen__row">
              <IconButton className="reader-listen__play" label={isSpeaking ? "Stop reading aloud" : "Read aloud"} icon={isSpeaking ? <Square /> : <Play />} onClick={toggleTts} />
              <span className="reader-listen__status">{isSpeaking ? "Reading aloud" : "Browser voice"}</span>
            </div>
          ) : (
            <p className="reader-listen__status">This browser can’t read aloud. Choose a self-hosted voice in Listen settings.</p>
          )}
          <div className="reader-listen__row reader-listen__row--end">
            <Select label="Speed" hideLabel options={rateOptions} value={String(ttsRate)} onChange={(event) => setTtsRate(Number(event.target.value))} fieldClassName="reader-listen__speed" />
            <IconButton label="Listen settings" icon={<Settings2 />} onClick={() => setSettingsOpen(true)} />
            <IconButton label="Close player" icon={<X />} onClick={close} />
          </div>
          {jobError && !chapterAudioReady && <p className="reader-listen__note">{jobError}</p>}
          {audioPlayerError && <p className="reader-listen__error" role="alert">{audioPlayerError}</p>}
        </section>
      )}

      <Sheet open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Listen settings" closeLabel="Close listen settings" className="reader-listen-sheet">
        <div className="reader-listen-settings">
          <Select
            label="Voice provider"
            hint={ttsEngine === "openai_compatible" ? TTS_PROVIDER_PRESETS.find((preset) => preset.id === ttsPreset)?.description : "Uses the voices built into this browser."}
            value={ttsEngine === "native" ? "native" : ttsPreset}
            onChange={(event) => {
              if (event.target.value === "native") setTtsEngine("native");
              else applyTtsPreset(event.target.value as TtsProviderPresetId);
            }}
            options={[{ value: "native", label: "Browser voice" }, ...TTS_PROVIDER_PRESETS.map((preset) => ({ value: preset.id, label: preset.label }))]}
          />
          {ttsEngine === "native" && ttsAvailable && (
            <Select
              label="Voice"
              fieldClassName="reader-listen-settings__voice"
              value={voiceName}
              onChange={(event) => setVoiceName(event.target.value)}
              options={[{ value: "", label: "System voice" }, ...voices.map((voice) => ({ value: voice.name, label: `${voice.name} (${voice.lang})` }))]}
            />
          )}
          <Select
            label="Sleep timer"
            value={String(sleepMinutes)}
            onChange={(event) => setSleepMinutes(Number(event.target.value))}
            options={[{ value: "0", label: "Off" }, ...[15, 30, 45, 60].map((m) => ({ value: String(m), label: `${m} minutes` }))]}
          />
          {ttsEngine === "openai_compatible" && (
            <>
              <Select
                label="Generate audio"
                hint={server
                  ? "The Nexus server must be able to reach this endpoint. Jobs keep running after you close the reader; API keys stay in this browser."
                  : "For localhost or your own endpoint that only this browser can reach. Audio is kept on this device."}
                value={ttsExecutionMode}
                onChange={(event) => { setTtsExecutionMode(event.target.value as "browser" | "server"); setProviderDiagnostic(null); }}
                options={[{ value: "browser", label: "In this browser" }, { value: "server", label: "On the Nexus server" }]}
              />
              <Input label="API base URL" value={providerConfig.baseUrl} onChange={(event) => setProvider({ baseUrl: event.target.value })} />
              <Input label="API key" type="password" autoComplete="off" value={providerConfig.apiKey} onChange={(event) => setProvider({ apiKey: event.target.value }, false)} />
              <Input label="Model" value={providerConfig.model} onChange={(event) => setProvider({ model: event.target.value })} />
              <Input label="Voice" value={providerConfig.voice} onChange={(event) => setProvider({ voice: event.target.value })} />
              <Input label="Language code" placeholder="en" value={providerConfig.languageCode || ""} onChange={(event) => setProvider({ languageCode: event.target.value })} />
              {server && (
                <div className="reader-listen-settings__actions">
                  <Button size="sm" onClick={() => void diagnoseProvider()}>Check provider</Button>
                  <Button size="sm" onClick={() => void diagnoseProvider(true)}>Preview voice</Button>
                </div>
              )}
              {providerSummary && <p className="text-sm text-muted">This chapter: {providerSummary}</p>}
              {chapterAudioReady && (
                <Button variant="danger" size="sm" icon={<Trash2 aria-hidden="true" />} onClick={() => void deleteChapterAudio()}>Delete this chapter’s audio</Button>
              )}
            </>
          )}
          {providerDiagnostic && <p className="text-sm" role="status">{providerDiagnostic}</p>}
        </div>
      </Sheet>
    </>
  );
};

export default ListenPlayer;
