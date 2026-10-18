import { chapterIdentity, chapterSourceVersion, expectedChapterIdentity, CHAPTER_MANIFEST_CHANGED } from "../../services/chapterIdentity";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw, Settings2, SkipBack, SkipForward, Square, Trash2, WandSparkles, X } from "lucide-react";
import { Button, IconButton, Input, Select, Sheet, Switch } from "../ui";
import { ChapterAudioJob, chapterAudioJobStore, chapterAudioStore } from "../../services/offlineReaderStore";
import { mergeAudioSegments, OpenAICompatibleTtsConfig, splitTextForSynthesis, TtsProviderPresetId, TTS_PROVIDER_PRESETS, TtsRequestError, ttsService } from "../../services/ttsService";
import { audioService, ServerAudioJob } from "../../services/audioService";
import { accountStorage, storageGeneration } from "../../services/accountStorage";
import type {ChapterDocument,TextLocator} from "./chapterDocument";
import {alignedTo,audioLocator,audioTime,measuredManifest,planAudioPassages,type AudioManifest} from "../../services/audioAlignment";
import { useAudioMediaSession } from "../../hooks/useAudioMediaSession";

export interface ListenChapter {
  id: number;
  chapter_number: number;
  chapter_key?: string;manifest_epoch?: string;manifest_revision?: string;
  title: string;
  content: string;
  document?: ChapterDocument;
}

interface ListenPlayerProps {
  chapter: ListenChapter;
  libraryId: number;
  novelId: number;
  /** The player is docked and visible. Closing it stops narration. */
  open: boolean;
  onClose: () => void;
  onPlayingChange?: (playing: boolean) => void;
  rendition?: string;
  readingLocator?: () => TextLocator | undefined;
  onReadPassage?: (locator:TextLocator) => void;
  onAudioPassage?: (locator:TextLocator, completed:boolean) => void;
  requestedChapterNumber?: number;
  chapterReady?: boolean;
  navigationKey?: string | number;
  nextChapterNumber?: number;
  onNextChapter?: () => void;
  audioCreationHref?: string;
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
const ListenPlayer: React.FC<ListenPlayerProps> = ({ chapter, libraryId: library_id, novelId: novel_id, open, onClose, onPlayingChange, rendition = "original", readingLocator, onReadPassage, onAudioPassage, requestedChapterNumber = chapter.chapter_number, chapterReady = true, navigationKey = requestedChapterNumber, nextChapterNumber, onNextChapter, audioCreationHref }) => {
  const chapter_number = chapter.chapter_number;
  const identityKey=chapterIdentity(chapter)?.chapter_key;
  const contextRef = useRef("");
  const playbackContext = `${storageGeneration()}:${novel_id}:${chapterIdentity(chapter)?.chapter_key || chapter.id}:${chapterIdentity(chapter)?.manifest_epoch || ""}:${chapterIdentity(chapter)?.manifest_revision || ""}:${requestedChapterNumber}`;
  contextRef.current = playbackContext;
  const isCurrent = useCallback(() => contextRef.current === playbackContext && playbackContext.startsWith(`${storageGeneration()}:`), [playbackContext]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [ttsAvailable] = useState(() => typeof window !== "undefined" && "speechSynthesis" in window);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceName, setVoiceName] = useState(() => accountStorage.getItem("nexus-reader-tts-voice") || "");
  const [ttsRate, setTtsRate] = useState(() => Number(accountStorage.getItem("nexus-reader-tts-rate")) || 1);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [ttsEngine, setTtsEngine] = useState<"native" | "openai_compatible">(() => (accountStorage.getItem("nexus-reader-tts-engine") as "native" | "openai_compatible") || "native");
  const [ttsPreset, setTtsPreset] = useState<TtsProviderPresetId | "qwen3_clone">(() => (accountStorage.getItem("nexus-reader-tts-preset") as TtsProviderPresetId) || "kokoro_mps");
  const [providerConfig, setProviderConfig] = useState<OpenAICompatibleTtsConfig>(() => ({
    baseUrl: accountStorage.getItem("nexus-reader-tts-url") || "http://localhost:8880/v1",
    apiKey: accountStorage.getItem("nexus-reader-tts-key") || "",
    model: accountStorage.getItem("nexus-reader-tts-model") || "kokoro",
    voice: accountStorage.getItem("nexus-reader-tts-provider-voice") || "af_bella",
    languageCode: accountStorage.getItem("nexus-reader-tts-language") || undefined,
  }));
  const [ttsExecutionMode, setTtsExecutionMode] = useState<"browser" | "server">(() => (accountStorage.getItem("nexus-reader-tts-execution") as "browser" | "server") || "browser");
  const [alignment,setAlignment] = useState<AudioManifest|null>(null);
  const alignmentRef = useRef<AudioManifest|null>(null);
  const lastReportedPassage = useRef("");
  const [includeNotes,setIncludeNotes] = useState(()=>accountStorage.getItem("nexus-reader-audio-notes")==="true");
  const reportPassageRef = useRef<(seconds:number,completed?:boolean)=>void>(()=>undefined);
  const [localAudioReady, setLocalAudioReady] = useState(false);
  const [audioJob, setAudioJob] = useState<ChapterAudioJob | null>(null);
  const [serverAudioJob, setServerAudioJob] = useState<ServerAudioJob | null>(null);
  const [localLoaded, setLocalLoaded] = useState("");
  const [serverLoaded, setServerLoaded] = useState("");
  const chapterAudioReady = localLoaded === playbackContext && localAudioReady || serverLoaded === playbackContext && Boolean(serverAudioJob?.audio_ready);
  const [continuous, setContinuous] = useState(() => accountStorage.getItem("nexus-reader-audio-continuous") === "true");
  const [continuation, setContinuation] = useState<{target: number; generation: number; story: number; navigation: string | number} | null>(null);
  const [sleepDeadline, setSleepDeadline] = useState<number | null>(null);
  const continuationRoute = useRef<string | number | null>(null);
  const playbackEpoch = useRef(0);
  const playingRef = useRef(false);
  const endedRef = useRef<() => void>(() => undefined);
  const [audioPlayerError, setAudioPlayerError] = useState<string | null>(null);
  const [audioCurrentTime, setAudioCurrentTime] = useState(0);
  const [audioDuration, setAudioDuration] = useState(0);
  const [sleepMinutes, setSleepMinutes] = useState(() => Number(accountStorage.getItem("nexus-reader-audio-sleep-minutes")) || 0);
  const [voiceProfileId] = useState<number | null>(() => Number(accountStorage.getItem("nexus-reader-narrator-id")) || null);
  const [providerDiagnostic, setProviderDiagnostic] = useState<string | null>(null);
  const providerAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioControllerRef = useRef<AbortController | null>(null);
  const audioObjectUrlRef = useRef<string | null>(null);
  const audioJobRunningRef = useRef(false);
  const playerLoadRef = useRef<{key:string;promise:Promise<HTMLAudioElement|null>}|null>(null);
  const metadataRef = useRef<{audio:HTMLAudioElement;promise:Promise<boolean>;resolve:(ready:boolean)=>void}|null>(null);
  const audioPlayEpoch = useRef(0);
  const deletingAudioContext = useRef<string | null>(null);

  useEffect(() => { onPlayingChange?.(isSpeaking); }, [isSpeaking, onPlayingChange]);

  useEffect(() => {
    // React may replay effects during development without rendering again.
    // Restore the context on setup, while a real unmount still invalidates it.
    contextRef.current = playbackContext;
    return () => { contextRef.current = ""; };
  }, [playbackContext]);
  useEffect(() => {
    if (!open) {
      playbackEpoch.current += 1; playingRef.current = false;
      providerAudioRef.current?.pause();
      if (ttsAvailable) window.speechSynthesis.cancel();
      setIsSpeaking(false); setContinuation(null); setSleepDeadline(null);
    }
  }, [open, ttsAvailable]);

  // Saved audio and local generation jobs for this chapter.
  useEffect(() => {
    let active = true;
    setLocalAudioReady(false);
    setAudioJob(null);
    setAudioDuration(0);
    void Promise.all([
      chapterAudioStore.get(novel_id, chapter_number),
      chapterAudioJobStore.get(novel_id, chapter_number),
    ]).then(([audio, job]) => {
      if (!active || !isCurrent()) return;
      setLocalLoaded(playbackContext);
      setLocalAudioReady(Boolean(audio));
      setAudioJob(job);
      setAudioCurrentTime(identityKey ? Number(accountStorage.getItem(`nexus-reader-audio-position-v2:${novel_id}:${identityKey}`)) || 0 : 0);
      setAudioPlayerError(null);
    }).catch(() => {
      if (!active || !isCurrent()) return;
      setLocalLoaded(playbackContext);
      setLocalAudioReady(false);
      setAudioJob(null);
    });
    return () => { active = false; };
  }, [novel_id, chapter_number, playbackContext, isCurrent,identityKey]);

  useEffect(() => { accountStorage.setItem("nexus-reader-tts-voice", voiceName); }, [voiceName]);

  useEffect(() => {
    accountStorage.setItem("nexus-reader-tts-rate", String(ttsRate));
    if (providerAudioRef.current) providerAudioRef.current.playbackRate = ttsRate;
  }, [ttsRate]);

  useEffect(() => {
    accountStorage.setItem("nexus-reader-tts-engine", ttsEngine);
    accountStorage.setItem("nexus-reader-tts-preset", ttsPreset);
    accountStorage.setItem("nexus-reader-tts-url", providerConfig.baseUrl);
    accountStorage.setItem("nexus-reader-tts-key", providerConfig.apiKey);
    accountStorage.setItem("nexus-reader-tts-model", providerConfig.model);
    accountStorage.setItem("nexus-reader-tts-provider-voice", providerConfig.voice);
    accountStorage.setItem("nexus-reader-tts-execution", ttsExecutionMode);
    if (providerConfig.languageCode) accountStorage.setItem("nexus-reader-tts-language", providerConfig.languageCode);
    else accountStorage.removeItem("nexus-reader-tts-language");
  }, [providerConfig, ttsEngine, ttsPreset, ttsExecutionMode]);

  useEffect(() => { accountStorage.setItem("nexus-reader-audio-notes",String(includeNotes)); },[includeNotes]);
  useEffect(() => { accountStorage.setItem("nexus-reader-audio-continuous", String(continuous)); }, [continuous]);
  useEffect(() => { accountStorage.setItem("nexus-reader-audio-sleep-minutes", String(sleepMinutes)); }, [sleepMinutes]);
  useEffect(() => {
    if (sleepDeadline === null) return;
    const timer = window.setTimeout(() => {
      playbackEpoch.current += 1;
      playingRef.current = false;
      providerAudioRef.current?.pause();
      if (ttsAvailable) window.speechSynthesis.cancel();
      setIsSpeaking(false); setContinuation(null); setSleepDeadline(null);
      setProviderDiagnostic("Sleep timer paused chapter audio.");
    }, Math.max(0, sleepDeadline - Date.now()));
    return () => window.clearTimeout(timer);
  }, [sleepDeadline, ttsAvailable]);
  const armSleepTimer = () => {
    if (sleepMinutes && (!sleepDeadline || sleepDeadline <= Date.now())) setSleepDeadline(Date.now() + sleepMinutes * 60_000);
  };
  endedRef.current = () => {
    if (!isCurrent() || !playingRef.current || !open || requestedChapterNumber !== chapter_number) return;
    playingRef.current = false; setIsSpeaking(false);
    if (continuous && nextChapterNumber !== undefined && onNextChapter && (!sleepDeadline || sleepDeadline > Date.now())) {
      continuationRoute.current = null;
      setContinuation({target: nextChapterNumber, generation: storageGeneration(), story: novel_id, navigation: navigationKey});
      onNextChapter();
    } else {setSleepDeadline(null);}
  };

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
      playbackEpoch.current += 1; playingRef.current = false;
      alignmentRef.current=null; setAlignment(null); lastReportedPassage.current="";
      metadataRef.current?.resolve(false);metadataRef.current=null;
      if (ttsAvailable) window.speechSynthesis.cancel();
      audioControllerRef.current?.abort();
      providerAudioRef.current?.pause();
      if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
      providerAudioRef.current = null;
      audioObjectUrlRef.current = null;
      setIsSpeaking(false);
    };
  }, [chapter.id, requestedChapterNumber, ttsAvailable]);

  const chapterId = chapter.id;
  useEffect(() => {
    let active = true;
    setServerAudioJob(null);
    audioService.list(chapterId).then((jobs) => {
      if (active && isCurrent()) {setServerLoaded(playbackContext); setServerAudioJob(jobs[0] || null);}
    }).catch(() => { if (active && isCurrent()) setServerLoaded(playbackContext); });
    return () => { active = false; };
  }, [chapterId, playbackContext, isCurrent]);

  const serverAudioJobId = serverAudioJob?.id;
  const serverAudioJobStatus = serverAudioJob?.status;
  useEffect(() => {
    if (serverAudioJobId === undefined || !["queued", "processing", "retry_wait"].includes(serverAudioJobStatus ?? "")) return;
    const timer = window.setInterval(() => {
      audioService.get(serverAudioJobId).then((job) => {
        if (isCurrent()) setServerAudioJob(job);
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [serverAudioJobId, serverAudioJobStatus, playbackContext, isCurrent]);

  const stopTts = useCallback(() => {
    playbackEpoch.current += 1; playingRef.current = false; setContinuation(null);
    if (ttsAvailable) window.speechSynthesis.cancel();
    providerAudioRef.current?.pause();
    setIsSpeaking(false);
  },[ttsAvailable]);

  useEffect(()=>{
    const changed=(event:Event)=>{
      const detail=(event as CustomEvent).detail,identity=chapterIdentity(chapter);
      if(detail?.novelId===novel_id && identity && (detail.manifest_epoch!==identity.manifest_epoch || detail.manifest_revision!==identity.manifest_revision)){
        stopTts();audioControllerRef.current?.abort();playbackEpoch.current++;
        setAudioPlayerError("The chapter list changed. Open the current story before resuming this recording.");
      }
    };
    window.addEventListener(CHAPTER_MANIFEST_CHANGED,changed);
    return ()=>window.removeEventListener(CHAPTER_MANIFEST_CHANGED,changed);
  },[chapter,novel_id,stopTts]);
  const close = () => { stopTts(); setSleepDeadline(null); setSettingsOpen(false); onClose(); };

  const audioPositionKey = () => identityKey ? `nexus-reader-audio-position-v2:${novel_id}:${identityKey}` : null;
  const storedAudioPosition = () => {const key=audioPositionKey();return key?accountStorage.getItem(key):null;};
  const saveAudioPosition = (value:string) => {const key=audioPositionKey();if(key)accountStorage.setItem(key,value);};

  const saveAudioJob = async (job: ChapterAudioJob) => {
    if (!isCurrent()) throw new DOMException("Reader changed", "AbortError");
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
        ...(chapterIdentity(chapter) ? expectedChapterIdentity(chapterIdentity(chapter)!,chapterSourceVersion(chapter,true)) : {}),
        chapter_number: chapter.chapter_number,
        include_author_notes: includeNotes,
        ...(ttsPreset === "qwen3_clone" ? {voice_profile_id: voiceProfileId ?? undefined} : {}),
        provider: {
          id: ttsPreset,
          base_url: providerConfig.baseUrl,
          model: providerConfig.model,
          voice: providerConfig.voice,
          language_code: providerConfig.languageCode,
          execution_mode: "server",
        },
      });
      if (!isCurrent()) return;
      setServerLoaded(playbackContext); setServerAudioJob(job);
      setAudioPlayerError(null);
    } catch (error) {
      setAudioPlayerError(error instanceof Error ? error.message : "Could not start the server audio job.");
    }
  };

  const generateChapterAudio = async () => {
    if (!chapterReady || requestedChapterNumber !== chapter_number) return;
    if (audioJob?.status === "generating" || audioJobRunningRef.current) return;
    if (ttsPreset === "qwen3_clone" || ttsExecutionMode === "server") {
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
      const planned = !existing?.chunks?.length && chapter.document ? planAudioPassages(chapter.document,chapter.title,isSparkProvider ? 380 : 1_100,includeNotes) : null;
      const chunks = existing?.chunks?.length
        ? (isSparkProvider && !existing.alignment_plan
          ? [
              ...existing.chunks.slice(0, completedChunks),
              ...existing.chunks.slice(completedChunks).flatMap((chunk) => splitTextForSynthesis(chunk, 380)),
            ]
          : existing.chunks)
        : planned ? planned.map(part=>part.text) : splitTextForSynthesis(`${chapter.title}. ${chapter.content}`, isSparkProvider ? 380 : 1_100);
      if (!chunks.length) {
        setAudioPlayerError("This chapter has no text to turn into audio.");
        return;
      }
      job = {
        ...chapterIdentity(chapter),cache_key: `${novel_id}:${chapterIdentity(chapter)?.chapter_key}`,
        novel_id,
        chapter_number: chapter.chapter_number,
        chunks,
        source_version: existing?.chunks?.length ? existing.source_version : chapter.document?.content_version,
        alignment_plan: existing?.alignment_plan || planned?.map(part=>part.passage),
        include_author_notes: existing?.include_author_notes ?? includeNotes,
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
        if (!isCurrent()) return;
        await chapterAudioJobStore.saveSegment(novel_id, chapter.chapter_number, index, audio,undefined,undefined,chapterIdentity(chapter) ?? undefined);
        job.completed_chunks = index + 1;
        await saveAudioJob(job);
      }
      const segments = await chapterAudioJobStore.segments(novel_id, chapter.chapter_number);
      let durations:number[]=[];
      const merged = await mergeAudioSegments(segments,values=>{durations=values;});
      if (!isCurrent()) return;
      const manifest = job.source_version && job.alignment_plan ? measuredManifest(job.source_version,job.alignment_plan,durations,job.include_author_notes,null,chapterIdentity(chapter) ?? undefined) : null;
      await chapterAudioStore.save(novel_id, chapter.chapter_number, merged, manifest);
      await chapterAudioJobStore.clearSegments(novel_id, chapter.chapter_number,undefined,undefined,chapterIdentity(chapter) ?? undefined);
      job.status = "ready";
      job.error = undefined;
      await saveAudioJob(job);
      setLocalLoaded(playbackContext); setLocalAudioReady(true);
    } catch (error) {
      if (!isCurrent()) return;
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

  const loadChapterAudioPlayer = (epoch = playbackEpoch.current): Promise<HTMLAudioElement | null> => {
    if (!isCurrent() || epoch !== playbackEpoch.current || deletingAudioContext.current===playbackContext) return Promise.resolve(null);
    if (providerAudioRef.current) return Promise.resolve(providerAudioRef.current);
    const key = `${playbackContext}:${epoch}`;
    if (playerLoadRef.current?.key === key) return playerLoadRef.current.promise;
    const promise = (async () => {
      let audioBlob:Blob|null=null, manifest:AudioManifest|null=null;
      if(serverAudioJob?.audio_ready){
        try {
          [audioBlob,manifest]=await Promise.all([audioService.audio(serverAudioJob.id), audioService.manifest?.(serverAudioJob.id).catch(()=>null) ?? Promise.resolve(null)]);
          if(isCurrent() && epoch === playbackEpoch.current && audioBlob) void chapterAudioStore.save?.(novel_id,chapter_number,audioBlob,manifest,()=>isCurrent() && epoch===playbackEpoch.current).catch(()=>undefined);
        } catch(error) {
          const cached=await chapterAudioStore.recording(novel_id,chapter_number);
          audioBlob=cached?.audio || null;manifest=cached?.manifest || null;
          if(!audioBlob || manifest?.job_id!==serverAudioJob.id)throw error;
        }
      } else {const cached=await chapterAudioStore.recording(novel_id,chapter_number);audioBlob=cached?.audio || null;manifest=cached?.manifest || null;}
      if (!isCurrent() || epoch !== playbackEpoch.current) return null;
      const identity=chapterIdentity(chapter);
      if(identity && (manifest?.chapter_key!==identity.chapter_key || manifest?.manifest_epoch!==identity.manifest_epoch))throw new Error("This recording belongs to a different chapter identity. Open the story to review the current chapter.");
      if (!audioBlob) {setLocalAudioReady(false);return null;}
      // A different load may have completed while this one was fetching.
      if (providerAudioRef.current) return providerAudioRef.current;
      alignmentRef.current=null; setAlignment(null);
      const audio = new Audio();
      const url = URL.createObjectURL(audioBlob);
      audioObjectUrlRef.current = url;
      providerAudioRef.current = audio;
      const ownsPlayer = () => isCurrent() && providerAudioRef.current === audio;
      let resolveMetadata:(ready:boolean)=>void = ()=>undefined;
      const metadataPromise = new Promise<boolean>(resolve=>{resolveMetadata=resolve;});
      metadataRef.current={audio,promise:metadataPromise,resolve:resolveMetadata};
      audio.preload = "metadata";
      audio.playbackRate = ttsRate;
      audio.onloadedmetadata = () => {
        if (!ownsPlayer()) return;
        const validDuration = Number.isFinite(audio.duration) && audio.duration > 0;
        setAudioDuration(validDuration ? audio.duration : 0);
        const measured=manifest?.duration_seconds;
        const verified=validDuration && measured !== null && measured !== undefined && Number.isFinite(measured) && Math.abs(audio.duration-measured)<=0.1;
        alignmentRef.current=verified ? manifest : null;setAlignment(verified ? manifest : null);
        const saved = Math.max(0,Number(storedAudioPosition()) || 0);
        audio.currentTime = Math.min(saved, validDuration ? audio.duration : saved);
        setAudioCurrentTime(audio.currentTime);
        resolveMetadata(verified);
      };
      audio.ontimeupdate = () => {
        if (!ownsPlayer()) return;
        setAudioCurrentTime(audio.currentTime);
        saveAudioPosition(String(audio.currentTime));
        if (playingRef.current) reportPassageRef.current(audio.currentTime);
      };
      audio.onended = () => {
        if (!ownsPlayer()) return;
        saveAudioPosition("0");
        if (playingRef.current) reportPassageRef.current(Math.max(0,(alignmentRef.current?.duration_seconds || 0)-0.001),true);
        setAudioCurrentTime(0);endedRef.current();
      };
      audio.onerror = () => {
        resolveMetadata(false);
        if (!ownsPlayer()) return;
        playingRef.current = false; setContinuation(null);
        setAudioPlayerError("The saved chapter audio could not be played. Generate it again to repair it.");setIsSpeaking(false);
      };
      audio.src = url;
      return audio;
    })();
    playerLoadRef.current={key,promise};
    void promise.finally(()=>{if(playerLoadRef.current?.promise===promise)playerLoadRef.current=null;}).catch(()=>undefined);
    return promise;
  };
  const waitForMetadata = async (audio:HTMLAudioElement) => {
    const metadata=metadataRef.current;
    if (!metadata || metadata.audio!==audio) return false;
    let timeout=0;
    try {return await Promise.race([metadata.promise,new Promise<boolean>(resolve=>{timeout=window.setTimeout(()=>resolve(false),15_000);})]);}
    finally {window.clearTimeout(timeout);}
  };

  reportPassageRef.current = (seconds,completed=false) => {
    if(!isCurrent() || !chapterReady || rendition!=="original")return;
    const locator=audioLocator(alignmentRef.current,chapter.document,seconds,rendition,chapterIdentity(chapter) ?? undefined);
    if(!locator)return;
    const key=`${locator.blockId}:${locator.textOffset}:${completed}`;
    if(key===lastReportedPassage.current)return;
    lastReportedPassage.current=key;onAudioPassage?.(locator,completed);
  };
  const playChapterAudio = async () => {
    if (!open || !chapterReady || requestedChapterNumber !== chapter_number || !isCurrent() || deletingAudioContext.current===playbackContext) return;
    if (playingRef.current) {stopTts(); return;}
    const epoch = ++playbackEpoch.current;
    try {
      const audio = await loadChapterAudioPlayer(epoch);
      if (!audio || !isCurrent() || epoch !== playbackEpoch.current) return;
      audio.playbackRate = ttsRate;
      audioPlayEpoch.current=epoch;
      await audio.play();
      if (!isCurrent() || epoch !== playbackEpoch.current || providerAudioRef.current !== audio) {
        if (audioPlayEpoch.current===epoch || providerAudioRef.current!==audio) audio.pause();
        return;
      }
      armSleepTimer(); playingRef.current = true;
      setIsSpeaking(true); setAudioPlayerError(null); reportPassageRef.current(audio.currentTime);
    } catch {
      if (isCurrent() && epoch===playbackEpoch.current) {playingRef.current = false; setAudioPlayerError("Tap Play to continue listening; your browser did not start audio automatically.");}
    }
  };

  const listenFromReading = async () => {
    const locator=readingLocator?.();
    const epoch=playbackEpoch.current;
    try {
      const audio=await loadChapterAudioPlayer(epoch);
      if(!audio || !isCurrent() || epoch!==playbackEpoch.current)return;
      await waitForMetadata(audio);
      if(!isCurrent() || epoch!==playbackEpoch.current || providerAudioRef.current!==audio)return;
      const seconds=audioTime(alignmentRef.current,chapter.document,locator,rendition,chapterIdentity(chapter) ?? undefined);
      if(seconds===undefined){setAudioPlayerError("This recording cannot be linked to the displayed passage. Use Play to listen without changing the reading position.");return;}
      stopTts(); audio.currentTime=seconds; saveAudioPosition(String(seconds));setAudioCurrentTime(seconds);
      // Metadata can arrive after a seek; restoring from the stored value keeps the same boundary.
      await playChapterAudio();
    } catch {if(isCurrent())setAudioPlayerError("Could not load the saved audio. Try Play again.");}
  };
  const readFromAudio = () => {
    const locator=audioLocator(alignmentRef.current,chapter.document,providerAudioRef.current?.currentTime ?? audioCurrentTime,rendition,chapterIdentity(chapter) ?? undefined);
    if(!locator)return;
    stopTts();onReadPassage?.(locator);
  };

  const setChapterAudioPosition = async (position: number, relative = false) => {
    const epoch=playbackEpoch.current;
    const audio = await loadChapterAudioPlayer(epoch);
    if (!audio || !isCurrent() || epoch!==playbackEpoch.current || providerAudioRef.current!==audio) return;
    const duration = Number.isFinite(audio.duration) ? audio.duration : audioDuration;
    const target = relative ? audio.currentTime + position : position;
    audio.currentTime = Math.max(0, Math.min(duration || Number.MAX_SAFE_INTEGER, target));
    setAudioCurrentTime(audio.currentTime);
    saveAudioPosition(String(audio.currentTime));
  };

  const deleteChapterAudio = async () => {
    if (!isCurrent() || deletingAudioContext.current===playbackContext) return;
    deletingAudioContext.current=playbackContext;
    stopTts();
    alignmentRef.current=null;setAlignment(null);metadataRef.current?.resolve(false);metadataRef.current=null;
    if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
    providerAudioRef.current = null;
    audioObjectUrlRef.current = null;
    try {
      if (serverAudioJob?.audio_ready) {
        await audioService.remove(serverAudioJob.id);
        await chapterAudioStore.removeForJob?.(novel_id,chapter_number,serverAudioJob.id);
        if(!isCurrent())return;
        setServerAudioJob(null);
      } else {
        await chapterAudioStore.remove(novel_id, chapter.chapter_number);
        await chapterAudioJobStore.remove(novel_id, chapter.chapter_number,undefined,undefined,chapterIdentity(chapter) ?? undefined);
        if(!isCurrent())return;
      }
      // Invalidate all work associated with the removed recording before
      // allowing another playback or load attempt.
      stopTts();
      setLocalAudioReady(false);setAudioJob(null);
      setAudioDuration(0);setAudioCurrentTime(0);
      const positionKey=audioPositionKey();if(positionKey)accountStorage.removeItem(positionKey);
    } catch (error) {
      if(isCurrent())setAudioPlayerError(error instanceof Error ? error.message : "Could not delete the saved audio.");
    } finally {
      if(deletingAudioContext.current===playbackContext)deletingAudioContext.current=null;
    }
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
    if (!chapterReady || requestedChapterNumber !== chapter_number || !open) return;
    if (ttsAvailable && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
      stopTts();
      return;
    }
    if (isSpeaking) { stopTts(); return; }
    if (ttsEngine === "openai_compatible") { return; }
    if (!ttsAvailable) return;
    const epoch = ++playbackEpoch.current;
    const utterance = new SpeechSynthesisUtterance(`${chapter.title}. ${chapter.content}`);
    const selectedVoice = voices.find((voice) => voice.name === voiceName);
    if (selectedVoice) utterance.voice = selectedVoice;
    utterance.rate = ttsRate;
    utterance.onend = () => {if (isCurrent() && epoch === playbackEpoch.current) endedRef.current();};
    utterance.onerror = () => {if (isCurrent() && epoch === playbackEpoch.current) {playingRef.current = false; setIsSpeaking(false); setContinuation(null); setAudioPlayerError("Browser narration stopped. Tap Read aloud to continue.");}};
    armSleepTimer(); playingRef.current = true; setIsSpeaking(true);
    window.speechSynthesis.speak(utterance);
  };

  useEffect(() => {
    if (!continuation) return;
    if (!open || !continuous || continuation.generation !== storageGeneration() || continuation.story !== novel_id ||
        requestedChapterNumber !== continuation.target || sleepDeadline !== null && sleepDeadline <= Date.now()) {
      // The old chapter can render once before the requested navigation arrives.
      if (navigationKey === continuation.navigation && requestedChapterNumber === chapter_number && chapter_number !== continuation.target && open && continuous && continuation.story === novel_id && continuation.generation === storageGeneration()) return;
      setContinuation(null); return;
    }
    if (continuationRoute.current !== null && continuationRoute.current !== navigationKey) {setContinuation(null); return;}
    continuationRoute.current = navigationKey;
    if (!chapterReady || chapter_number !== continuation.target) return;
    if (ttsEngine === "openai_compatible" && !chapterAudioReady && (localLoaded !== playbackContext || serverLoaded !== playbackContext)) return;
    setContinuation(null);
    if(identityKey)accountStorage.setItem(`nexus-reader-audio-position-v2:${novel_id}:${identityKey}`, "0");
    if (ttsEngine === "native") toggleTts();
    else if (chapterAudioReady) void playChapterAudio();
    else setAudioPlayerError("The next chapter needs audio. Generate it or tap Play when it is ready; no generation was started automatically.");
  // A continuation is a one-use intent, never a playback preference or history state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [continuation, chapter_number, requestedChapterNumber, chapterReady, localLoaded, serverLoaded, chapterAudioReady, open, continuous, sleepDeadline, novel_id, playbackContext, ttsEngine, navigationKey]);

  useAudioMediaSession({
    active: open, playing: isSpeaking, title: chapter.title,
    onPlay: () => {
      if (isSpeaking) return;
      if (ttsEngine === "openai_compatible") void playChapterAudio();
      else if (ttsAvailable && window.speechSynthesis.paused) { window.speechSynthesis.resume(); armSleepTimer(); playingRef.current = true; setIsSpeaking(true); }
      else toggleTts();
    },
    onPause: () => { if (ttsEngine === "openai_compatible") playbackEpoch.current += 1; playingRef.current = false; setContinuation(null); providerAudioRef.current?.pause(); if (ttsAvailable) window.speechSynthesis.pause(); setIsSpeaking(false); },
    onStop: () => {stopTts(); setSleepDeadline(null);},
    onSeek: ttsEngine === "openai_compatible" ? (seconds, relative) => { void setChapterAudioPosition(seconds, relative); } : undefined,
  });

  const server = ttsPreset === "qwen3_clone" || ttsExecutionMode === "server";
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
                {audioCreationHref ? <a className="reader-listen__create-link" href={audioCreationHref}>Create audio for this story</a> : <><Button variant="primary" size="sm" icon={<WandSparkles aria-hidden="true" />} loading={generating} disabled={generating} onClick={() => void generateChapterAudio()}>
                  {generating ? "Generating…" : done ? "Resume generation" : "Generate chapter audio"}
                </Button>
                {pausable && <Button size="sm" variant="ghost" icon={<Pause aria-hidden="true" />} onClick={() => void cancelAudioGeneration()}>Pause</Button>}
                {retryable && <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden="true" />} onClick={() => void generateChapterAudio()}>Retry</Button>}</>}
                {audioCreationHref && ttsPreset !== "qwen3_clone" && <span className="reader-listen__note">This chapter uses {TTS_PROVIDER_PRESETS.find(preset => preset.id === ttsPreset)?.label || "your configured voice"}.</span>}
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
          {ttsEngine === "openai_compatible" && chapterAudioReady && <div className="reader-listen__row">
            {readingLocator && rendition === "original" && <Button size="sm" variant="ghost" onClick={()=>void listenFromReading()}>Listen from this passage</Button>}
            {onReadPassage && alignedTo(alignment,chapter.document,rendition,chapterIdentity(chapter) ?? undefined) && <Button size="sm" variant="ghost" disabled={!audioLocator(alignment,chapter.document,audioCurrentTime,rendition,chapterIdentity(chapter) ?? undefined)} onClick={readFromAudio}>Read this passage</Button>}
          </div>}
          {providerAudioRef.current && ttsEngine === "openai_compatible" && !alignedTo(alignment,chapter.document,rendition,chapterIdentity(chapter) ?? undefined) && <p className="reader-listen__note">{alignment?.source_version && alignment.source_version !== chapter.document?.content_version ? "This recording uses an earlier chapter version. It remains playable; passage links and reading progress are paused." : rendition !== "original" ? "This recording uses the original text. Switch to the original for passage links." : "This recording has no verified passage timings. It remains playable."}</p>}
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
              else if (event.target.value === "qwen3_clone") {setTtsEngine("openai_compatible"); setTtsPreset("qwen3_clone"); setTtsExecutionMode("server");}
              else applyTtsPreset(event.target.value as TtsProviderPresetId);
            }}
            options={[{ value: "native", label: "Browser voice" }, {value: "qwen3_clone", label: "My cloned narrator · local Qwen3"}, ...TTS_PROVIDER_PRESETS.map((preset) => ({ value: preset.id, label: preset.label }))]}
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
          {!audioCreationHref && <Switch label="Narrate author notes" checked={includeNotes} onChange={setIncludeNotes} aria-description="Applies when generating new audio; existing recordings are preserved." />}
          <Switch label="Continue to next chapter" aria-description="Play saved chapter audio in order. Pause when the next chapter needs audio." checked={continuous} onChange={(checked) => {setContinuous(checked); if (!checked) setContinuation(null);}} />
          <Select
            label="Sleep timer"
            value={String(sleepMinutes)}
            onChange={(event) => {const minutes = Number(event.target.value); setSleepMinutes(minutes); setSleepDeadline(minutes && (playingRef.current || continuation) ? Date.now() + minutes * 60_000 : null);}}
            options={[{ value: "0", label: "Off" }, ...[15, 30, 45, 60].map((m) => ({ value: String(m), label: `${m} minutes` }))]}
          />
          {(audioCreationHref || ttsPreset === "qwen3_clone") && ttsEngine === "openai_compatible" && <>
            <p className="text-sm text-muted">Manage your narrators in Settings. Choose a narrator and chapters from the story’s Audio tab.</p>
            {providerSummary && <p className="text-sm text-muted">This chapter: {providerSummary}</p>}
            {chapterAudioReady && <Button variant="danger" size="sm" icon={<Trash2 aria-hidden="true" />} onClick={() => void deleteChapterAudio()}>Delete this chapter’s audio</Button>}
          </>}
          {!audioCreationHref && ttsEngine === "openai_compatible" && ttsPreset !== "qwen3_clone" && (
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
          <a href="/settings/voices">Manage narrator voices in Settings</a>
          {audioCreationHref && <a href={audioCreationHref}>Create audio for this story</a>}
          {providerDiagnostic && <p className="text-sm" role="status">{providerDiagnostic}</p>}
        </div>
      </Sheet>
    </>
  );
};

export default ListenPlayer;
