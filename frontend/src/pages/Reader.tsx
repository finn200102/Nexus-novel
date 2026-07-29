import React, { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useNavigate, useParams } from "react-router-dom";
import { Pause, Play, RotateCcw, SkipBack, SkipForward, Trash2, Volume2, WandSparkles } from "lucide-react";
import { chapterService } from "../services/chapterService";
import { novelService } from "../services/novelService";
import { ChapterAudioJob, chapterAudioJobStore, chapterAudioStore, offlineReaderStore } from "../services/offlineReaderStore";
import { mergeAudioSegments, OpenAICompatibleTtsConfig, splitTextForSynthesis, TtsProviderPresetId, TTS_PROVIDER_PRESETS, TtsRequestError, ttsService } from "../services/ttsService";
import { audioService, ServerAudioJob } from "../services/audioService";
import "../styles/Reader.css";

interface ChapterContent {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
}

interface Novel {
  id: number;
  title: string;
  author: string;
  library_id: number;
  total_chapters: number;
}

interface ChapterSummary {
  id: number;
  chapter_number: number;
  title: string;
}

interface ReadingProgress {
  chapter_number: number | null;
  position: number;
  percent: number;
}

interface ReadingAnnotation {
  id: number;
  chapter_number: number;
  annotation_type: "bookmark" | "note" | "highlight";
  position: number;
  percent: number;
  quote?: string | null;
  note?: string | null;
}

const themeOptions: { value: "night" | "dusk" | "paper"; label: string }[] = [
  { value: "night", label: "Night" },
  { value: "dusk", label: "Dusk" },
  { value: "paper", label: "Paper" },
];

const formatAudioTime = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const wholeSeconds = Math.floor(seconds);
  return `${Math.floor(wholeSeconds / 60)}:${String(wholeSeconds % 60).padStart(2, "0")}`;
};

const Reader: React.FC = () => {
  const { libraryId, novelId, chapterNumber } = useParams<{
    libraryId: string;
    novelId: string;
    chapterNumber: string;
  }>();
  const navigate = useNavigate();

  const chapter_number = Number(chapterNumber);
  const library_id = Number(libraryId);
  const novel_id = Number(novelId);

  const [chapter, setChapter] = useState<ChapterContent | null>(null);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState<boolean>(true);
  const [chaptersError, setChaptersError] = useState<string | null>(null);
  const [fontScale, setFontScale] = useState(() => Number(localStorage.getItem("nexus-reader-font-scale")) || 1);
  const [theme, setTheme] = useState<"night" | "dusk" | "paper">(() => (localStorage.getItem("nexus-reader-theme") as "night" | "dusk" | "paper") || "night");
  const [progress, setProgress] = useState<ReadingProgress | null>(null);
  const [annotations, setAnnotations] = useState<ReadingAnnotation[]>([]);
  const [restoredPosition, setRestoredPosition] = useState(false);
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
  const [offlineChapterCount, setOfflineChapterCount] = useState(0);
  const [chapterAudioReady, setChapterAudioReady] = useState(false);
  const [audioJob, setAudioJob] = useState<ChapterAudioJob | null>(null);
  const [serverAudioJob, setServerAudioJob] = useState<ServerAudioJob | null>(null);
  const [audioPlayerError, setAudioPlayerError] = useState<string | null>(null);
  const [audioCurrentTime, setAudioCurrentTime] = useState(0);
  const [audioDuration, setAudioDuration] = useState(0);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const providerAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioControllerRef = useRef<AbortController | null>(null);
  const audioObjectUrlRef = useRef<string | null>(null);
  const audioJobRunningRef = useRef(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const chapterData = await chapterService.getChapterContentByNumber(chapter_number, library_id, novel_id);
        const savedProgress = await chapterService.getReadingProgress(novel_id).catch(() => null);
        setChapter(chapterData);
        setProgress(savedProgress);
        setRestoredPosition(false);
        void Promise.all([
          chapterAudioStore.get(novel_id, chapter_number),
          chapterAudioJobStore.get(novel_id, chapter_number),
        ]).then(([audio, job]) => {
          setChapterAudioReady(Boolean(audio));
          setAudioJob(job);
          setAudioCurrentTime(Number(localStorage.getItem(`nexus-reader-audio-position-${novel_id}-${chapter_number}`)) || 0);
          setAudioPlayerError(null);
        }).catch(() => {
          setChapterAudioReady(false);
          setAudioJob(null);
        });
        localStorage.setItem(`nexus-reader-chapter-${novel_id}-${chapter_number}`, JSON.stringify(chapterData));
        void offlineReaderStore.save(chapterData).then(() => offlineReaderStore.countForNovel(novel_id)).then(setOfflineChapterCount).catch(() => undefined);

        if (chapterData && chapterData.novel_id) {
          const novelData = await novelService.getNovelById(
            library_id,
            chapterData.novel_id
          );
          setNovel(novelData);
        }
        setError(null);
      } catch (err) {
        const offlineChapter = await offlineReaderStore.get(novel_id, chapter_number).catch(() => null);
        const cached = localStorage.getItem(`nexus-reader-chapter-${novel_id}-${chapter_number}`);
        if (offlineChapter || cached) {
          setChapter(offlineChapter || JSON.parse(cached!));
          setProgress(null);
          setError("Offline mode: showing the last cached copy.");
        } else {
          const detail = axios.isAxiosError(err) ? String(err.response?.data?.detail || "") : "";
          setError(detail === "Chapter content is not downloaded"
            ? "This chapter has not been downloaded yet. Queue it from the novel page, then return here to read or generate audio."
            : "Failed to load content. Please try again later.");
        }
        console.error("Error fetching data:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [chapter_number, library_id, novel_id]);

  useEffect(() => {
    chapterService.getReadingAnnotations(novel_id)
      .then(setAnnotations)
      .catch((err) => console.error("Failed to load reader annotations", err));
  }, [novel_id]);

  useEffect(() => {
    localStorage.setItem("nexus-reader-font-scale", String(fontScale));
  }, [fontScale]);

  useEffect(() => {
    localStorage.setItem("nexus-reader-theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("nexus-reader-tts-voice", voiceName);
  }, [voiceName]);

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
      if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
      providerAudioRef.current = null;
      audioObjectUrlRef.current = null;
    };
  }, [chapter?.id, ttsAvailable]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter || !progress || progress.chapter_number !== chapter.chapter_number) return;
    window.requestAnimationFrame(() => {
      content.scrollTop = progress.position || ((progress.percent / 100) * Math.max(content.scrollHeight - content.clientHeight, 0));
      setRestoredPosition(true);
    });
  }, [chapter, progress]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.key === "ArrowLeft") goToChapter(chapter_number - 1);
      if (event.key === "ArrowRight") goToChapter(chapter_number + 1);
      if (event.key.toLowerCase() === "b") void addAnnotation("bookmark");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [chapter_number]);

  useEffect(() => {
    const fetchChapters = async () => {
      if (!novel_id) return;
      try {
        setChaptersLoading(true);
        const list = await chapterService.getChapters(novel_id);
        if (Array.isArray(list)) {
          const sorted = [...list].sort(
            (a, b) => a.chapter_number - b.chapter_number
          );
          setChapters(sorted);
          setChaptersError(null);
        } else {
          setChapters([]);
        }
      } catch (err) {
        console.error("Failed to load chapter list", err);
        setChaptersError("Unable to load chapters");
      } finally {
        setChaptersLoading(false);
      }
    };

    fetchChapters();
  }, [novel_id]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || !chapter) return;
    let timeout: number | undefined;
    const saveProgress = () => {
      const maxScroll = Math.max(content.scrollHeight - content.clientHeight, 1);
      const percent = Math.min(100, Math.max(0, (content.scrollTop / maxScroll) * 100));
      window.clearTimeout(timeout);
      timeout = window.setTimeout(() => {
        chapterService.updateReadingProgress(
          novel_id,
          chapter.chapter_number,
          Math.round(content.scrollTop),
          percent
        ).catch((err) => console.error("Failed to save reading progress", err));
      }, 500);
    };
    content.addEventListener("scroll", saveProgress, { passive: true });
    return () => {
      content.removeEventListener("scroll", saveProgress);
      window.clearTimeout(timeout);
    };
  }, [chapter, novel_id, restoredPosition]);

  const goToChapter = (target: number) => {
    navigate(`/library/${library_id}/novels/${novel_id}/${target}`);
  };

  const decreaseFont = () => setFontScale((prev) => Math.max(0.85, prev - 0.1));
  const increaseFont = () => setFontScale((prev) => Math.min(1.3, prev + 0.1));

  const keepChapterOffline = async () => {
    if (!chapter) return;
    await offlineReaderStore.save(chapter);
    setOfflineChapterCount(await offlineReaderStore.countForNovel(novel_id));
  };

  const stopTts = () => {
    if (ttsAvailable) window.speechSynthesis.cancel();
    providerAudioRef.current?.pause();
    setIsSpeaking(false);
  };

  const audioPositionKey = () => `nexus-reader-audio-position-${novel_id}-${chapter_number}`;

  const saveAudioJob = async (job: ChapterAudioJob) => {
    await chapterAudioJobStore.save(job);
    setAudioJob({ ...job, updated_at: Date.now() });
  };

  const generateServerAudio = async () => {
    if (!chapter) return;
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
    if (!chapter || audioJob?.status === "generating" || audioJobRunningRef.current) return;
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
        job.error = "Generation cancelled. You can resume from the last completed part.";
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

  useEffect(() => {
    if (!chapter) return;
    let active = true;
    audioService.list(chapter.id).then((jobs) => {
      if (active && jobs[0]) setServerAudioJob(jobs[0]);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [chapter?.id]);

  useEffect(() => {
    if (!serverAudioJob || !["queued", "processing", "retry_wait"].includes(serverAudioJob.status)) return;
    const timer = window.setInterval(() => {
      audioService.get(serverAudioJob.id).then((job) => {
        setServerAudioJob(job);
        if (job.audio_ready) setChapterAudioReady(true);
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [serverAudioJob?.id, serverAudioJob?.status]);

  const loadChapterAudioPlayer = async (): Promise<HTMLAudioElement | null> => {
    if (!chapter) return null;
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
    if (!chapter) return;
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

  const seekChapterAudio = async (seconds: number) => {
    const audio = await loadChapterAudioPlayer();
    if (!audio) return;
    const duration = Number.isFinite(audio.duration) ? audio.duration : audioDuration;
    audio.currentTime = Math.max(0, Math.min(duration || Number.MAX_SAFE_INTEGER, audio.currentTime + seconds));
    setAudioCurrentTime(audio.currentTime);
    localStorage.setItem(audioPositionKey(), String(audio.currentTime));
  };

  const setChapterAudioPosition = async (position: number) => {
    const audio = await loadChapterAudioPlayer();
    if (!audio) return;
    const duration = Number.isFinite(audio.duration) ? audio.duration : audioDuration;
    audio.currentTime = Math.max(0, Math.min(duration || Number.MAX_SAFE_INTEGER, position));
    setAudioCurrentTime(audio.currentTime);
    localStorage.setItem(audioPositionKey(), String(audio.currentTime));
  };

  const deleteChapterAudio = async () => {
    if (!chapter) return;
    stopTts();
    if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
    providerAudioRef.current = null;
    audioObjectUrlRef.current = null;
    await chapterAudioStore.remove(novel_id, chapter.chapter_number);
    await chapterAudioJobStore.remove(novel_id, chapter.chapter_number);
    setChapterAudioReady(false);
    setAudioJob(null);
    setAudioDuration(0);
    setAudioCurrentTime(0);
    localStorage.removeItem(audioPositionKey());
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
    if (!chapter) return;
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

  const addAnnotation = async (annotationType: "bookmark" | "note") => {
    if (!chapter || !contentRef.current) return;
    const content = contentRef.current;
    const maxScroll = Math.max(content.scrollHeight - content.clientHeight, 1);
    const percent = Math.min(100, Math.max(0, (content.scrollTop / maxScroll) * 100));
    const selection = window.getSelection()?.toString().trim() || "";
    const note = annotationType === "note" ? window.prompt("Private note (optional)") : null;
    if (annotationType === "note" && note === null) return;
    try {
      const created = await chapterService.createReadingAnnotation(novel_id, {
        chapter_number: chapter.chapter_number,
        annotation_type: annotationType,
        position: Math.round(content.scrollTop),
        percent,
        quote: selection || undefined,
        note: note || undefined,
      });
      setAnnotations((current) => [created, ...current]);
    } catch (err) {
      console.error("Failed to save reader annotation", err);
    }
  };

  const removeAnnotation = async (id: number) => {
    await chapterService.deleteReadingAnnotation(id);
    setAnnotations((current) => current.filter((annotation) => annotation.id !== id));
  };

  const exportReadingState = () => {
    const payload = {
      exported_at: new Date().toISOString(),
      novel_id: novel_id,
      novel_title: novel?.title,
      progress,
      annotations,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nexus-reading-state-${novel_id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loading) return <div className="reader-loading">Loading content...</div>;
  if (error && !chapter) return <div className="reader-error">{error}</div>;
  if (!chapter || !novel)
    return <div className="reader-not-found">Content not found</div>;

  const readerClass = `reader-shell reader-shell--${theme}`;
  const audioProgress = ttsExecutionMode === "server"
    ? (serverAudioJob?.total_parts ? Math.round((serverAudioJob.completed_parts / serverAudioJob.total_parts) * 100) : 0)
    : (audioJob?.chunks.length ? Math.round((audioJob.completed_chunks / audioJob.chunks.length) * 100) : 0);
  const audioJobLabel = ttsExecutionMode === "server"
    ? serverAudioJob?.status === "processing"
      ? `Generating ${serverAudioJob.completed_parts}/${serverAudioJob.total_parts} parts on Nexus`
      : serverAudioJob?.status === "queued"
        ? "Queued on Nexus server"
        : serverAudioJob?.status === "retry_wait"
          ? `Retry scheduled · ${serverAudioJob.completed_parts}/${serverAudioJob.total_parts} parts saved`
          : serverAudioJob?.status === "failed"
            ? `Failed at part ${serverAudioJob.completed_parts + 1}/${serverAudioJob.total_parts}`
            : serverAudioJob?.status === "cancelled"
              ? `Paused at ${serverAudioJob.completed_parts}/${serverAudioJob.total_parts} parts`
              : chapterAudioReady ? "Ready to play" : "Not generated"
    : audioJob?.status === "generating"
    ? `Generating ${audioJob.completed_chunks}/${audioJob.chunks.length} parts`
    : audioJob?.status === "queued"
      ? `Queued · ${audioJob.completed_chunks}/${audioJob.chunks.length} parts saved`
      : audioJob?.status === "failed"
        ? `Failed at part ${audioJob.completed_chunks + 1}/${audioJob.chunks.length}`
        : audioJob?.status === "cancelled"
          ? `Paused at ${audioJob.completed_chunks}/${audioJob.chunks.length} parts`
          : chapterAudioReady ? "Ready to play" : "Not generated";

  return (
    <div className={readerClass}>
      <aside className="reader-sidebar">
        <div className="reader-sidebar__header">
          <p>Chapters</p>
          <span>
            {chapter.chapter_number}/{novel.total_chapters}
          </span>
        </div>
        <div className="reader-sidebar__list">
          {chaptersLoading && (
            <p className="reader-sidebar__status">Loading…</p>
          )}
          {chaptersError && (
            <p className="reader-sidebar__status reader-sidebar__status--error">
              {chaptersError}
            </p>
          )}
          {!chaptersLoading && !chaptersError && (
            <ul>
              {chapters.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={
                      item.chapter_number === chapter.chapter_number
                        ? "is-active"
                        : ""
                    }
                    onClick={() => goToChapter(item.chapter_number)}
                  >
                    <span className="chapter-number">{item.chapter_number}</span>
                    <span className="chapter-title">{item.title || "Untitled"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <article className="reader-body">
        {error && <div className="reader-sidebar__status">{error}</div>}
        <header className="reader-toolbar">
          <div>
            <p className="reader-toolbar__eyebrow">{novel.author}</p>
            <h1>{chapter.title}</h1>
            <span>Chapter {chapter.chapter_number}</span>
          </div>
          <div className="reader-toolbar__controls">
            <div className="reader-toolbar__actions" aria-label="Reader actions">
              <div className="reader-type-controls" aria-label="Text size">
                <button type="button" onClick={decreaseFont} aria-label="Decrease text size">A−</button>
                <button type="button" onClick={increaseFont} aria-label="Increase text size">A+</button>
              </div>
              <div className="reader-type-controls" aria-label="Chapter actions">
                <button type="button" onClick={() => void addAnnotation("bookmark")}>Bookmark</button>
                <button type="button" onClick={() => void addAnnotation("note")}>Note</button>
                <button type="button" onClick={exportReadingState}>Export</button>
                <button type="button" onClick={() => void keepChapterOffline()}>Offline {offlineChapterCount}</button>
              </div>
            </div>
          </div>
        </header>

        <section className="reader-audio-panel" aria-label="Chapter audio">
          <div className="reader-audio-panel__header">
            <div>
              <span className="reader-audio-panel__eyebrow"><Volume2 size={14} /> AUDIOBOOK</span>
              <strong>Chapter audio</strong>
              <span className={`reader-audio-status reader-audio-status--${ttsExecutionMode === "server" ? serverAudioJob?.status || "idle" : audioJob?.status || "idle"}`}>{audioJobLabel}</span>
            </div>
            {ttsExecutionMode === "server" && serverAudioJob ? <small className="reader-audio-provider">{serverAudioJob.provider_model} · {serverAudioJob.provider_voice} · durable</small> : audioJob?.provider && <small className="reader-audio-provider">{audioJob.provider.model} · {audioJob.provider.voice} · local-only</small>}
          </div>
          {ttsEngine === "openai_compatible" ? (
            <>
              {((ttsExecutionMode === "server" && serverAudioJob && ["queued", "processing", "retry_wait", "failed", "cancelled"].includes(serverAudioJob.status)) || (ttsExecutionMode !== "server" && (audioJob?.status === "generating" || audioJob?.status === "queued" || audioJob?.status === "failed" || audioJob?.status === "cancelled"))) && (
                <div className="reader-audio-progress" aria-live="polite">
                  <div><span>{audioJobLabel}</span><strong>{audioProgress}%</strong></div>
                  <progress value={ttsExecutionMode === "server" ? serverAudioJob?.completed_parts || 0 : audioJob?.completed_chunks || 0} max={ttsExecutionMode === "server" ? serverAudioJob?.total_parts || 1 : audioJob?.chunks.length || 1} />
                  {(ttsExecutionMode === "server" ? serverAudioJob?.error : audioJob?.error) && <small>{ttsExecutionMode === "server" ? serverAudioJob?.error : audioJob?.error}</small>}
                </div>
              )}
              {chapterAudioReady ? (
                <div className="reader-audio-player">
                  <div className="reader-audio-player__transport">
                    <button type="button" onClick={() => void seekChapterAudio(-15)} aria-label="Back 15 seconds"><SkipBack size={17} /><span>15</span></button>
                    <button type="button" className="reader-audio-player__primary" onClick={() => void playChapterAudio()} aria-label={isSpeaking ? "Pause chapter audio" : "Play chapter audio"}>{isSpeaking ? <Pause size={21} fill="currentColor" /> : <Play size={21} fill="currentColor" />}</button>
                    <button type="button" onClick={() => void seekChapterAudio(15)} aria-label="Forward 15 seconds"><SkipForward size={17} /><span>15</span></button>
                  </div>
                  <label className="reader-audio-scrubber" aria-label="Audio progress"><span>{formatAudioTime(audioCurrentTime)}</span><input type="range" min="0" max={Math.max(audioDuration, 1)} step="0.1" value={Math.min(audioCurrentTime, Math.max(audioDuration, 1))} onChange={(event) => void setChapterAudioPosition(Number(event.target.value))} /><span>{formatAudioTime(audioDuration)}</span></label>
                  <div className="reader-audio-player__settings"><label>Speed <select aria-label="Chapter audio speed" value={ttsRate} onChange={(event) => setTtsRate(Number(event.target.value))}>{[0.8, 1, 1.2, 1.4, 1.6].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}</select></label><button type="button" className="reader-audio-player__delete" onClick={() => void deleteChapterAudio()} aria-label="Delete chapter audio"><Trash2 size={16} /></button></div>
                </div>
              ) : (
                <div className="reader-audio-actions">
                  <button type="button" className="reader-audio-player__primary" onClick={() => void generateChapterAudio()} disabled={ttsExecutionMode === "server" ? ["queued", "processing"].includes(serverAudioJob?.status || "") : audioJob?.status === "generating"}>{(ttsExecutionMode === "server" ? ["queued", "processing"].includes(serverAudioJob?.status || "") : audioJob?.status === "generating") ? "Generating…" : <><WandSparkles size={17} /> {(ttsExecutionMode === "server" ? serverAudioJob?.completed_parts : audioJob?.completed_chunks) ? "Resume generation" : "Generate chapter audio"}</>}</button>
                  {(ttsExecutionMode === "server" ? ["queued", "processing", "retry_wait"].includes(serverAudioJob?.status || "") : audioJob?.status === "generating") && <button type="button" onClick={() => void cancelAudioGeneration()}><Pause size={16} /> Pause generation</button>}
                  {(ttsExecutionMode === "server" ? ["failed", "cancelled", "retry_wait"].includes(serverAudioJob?.status || "") : audioJob?.status === "failed" || audioJob?.status === "cancelled") && <button type="button" onClick={() => void generateChapterAudio()}><RotateCcw size={16} /> Retry</button>}
                </div>
              )}
            </>
          ) : ttsAvailable ? (
            <div className="reader-audio-actions">
              <button type="button" className="reader-audio-player__primary" onClick={toggleTts}>{isSpeaking ? "Stop reading" : "Read aloud"}</button>
              <select aria-label="Text to speech voice" value={voiceName} onChange={(event) => setVoiceName(event.target.value)}><option value="">System voice</option>{voices.map((voice) => <option key={`${voice.name}-${voice.lang}`} value={voice.name}>{voice.name} ({voice.lang})</option>)}</select>
              <label>Speed <select aria-label="Text to speech speed" value={ttsRate} onChange={(event) => setTtsRate(Number(event.target.value))}>{[0.8, 1, 1.2, 1.4, 1.6].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}</select></label>
            </div>
          ) : <small>Browser text-to-speech is unavailable. Choose Self-hosted / API to generate chapter audio.</small>}
          {audioPlayerError && <p className="reader-audio-error" role="alert">{audioPlayerError}</p>}
        </section>

        <div
          ref={contentRef}
          className="reader-content"
          style={{ fontSize: `${1.05 * fontScale}rem` }}
        >
          {chapter.content.split("\n").map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>

        <div className="reader-navigation">
          <button
            className="prev-button"
            onClick={() => goToChapter(chapter.chapter_number - 1)}
            disabled={chapter.chapter_number <= 1}
          >
            Previous
          </button>
          <button
            className="next-button"
            onClick={() => goToChapter(chapter.chapter_number + 1)}
            disabled={chapter.chapter_number >= novel.total_chapters}
          >
            Next
          </button>
        </div>
      </article>
      <aside className="reader-inspector" aria-label="Reader settings and notes">
        <section className="reader-inspector__section">
          <header><strong>Reader</strong></header>
          <label>Theme</label>
          <div className="reader-theme-controls">
            {themeOptions.map((option) => <button key={option.value} type="button" className={theme === option.value ? "is-active" : ""} onClick={() => setTheme(option.value)}>{option.label}</button>)}
          </div>
        </section>
        <section className="reader-inspector__section">
          <header><strong>TTS settings</strong></header>
          <label htmlFor="reader-tts-provider">Provider</label>
          <select id="reader-tts-provider" value={ttsEngine === "native" ? "native" : ttsPreset} onChange={(event) => {
            if (event.target.value === "native") setTtsEngine("native");
            else applyTtsPreset(event.target.value as TtsProviderPresetId);
          }}>
            <option value="native">Browser voice</option>
            {TTS_PROVIDER_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
          </select>
          {ttsEngine === "openai_compatible" && <small>{TTS_PROVIDER_PRESETS.find((preset) => preset.id === ttsPreset)?.description}</small>}
          {ttsEngine === "openai_compatible" && !chapterAudioReady && <button type="button" className="reader-tts-generate" onClick={() => void generateChapterAudio()} disabled={audioJob?.status === "generating"}><WandSparkles size={16} /> {audioJob?.status === "generating" ? "Generating chapter…" : "Generate chapter audio"}</button>}
          <label htmlFor="reader-tts-speed">Playback speed <span>{ttsRate}×</span></label>
          <input id="reader-tts-speed" type="range" min="0.8" max="1.6" step="0.2" value={ttsRate} onChange={(event) => setTtsRate(Number(event.target.value))} />
          <details className="reader-tts-provider"><summary>Connection & voice</summary><label>Generation location<select value={ttsExecutionMode} onChange={(event) => setTtsExecutionMode(event.target.value as "browser" | "server")}><option value="browser">This browser (local-only)</option><option value="server">Nexus server (durable)</option></select></label><small>{ttsExecutionMode === "server" ? "The Nexus server must be able to reach this endpoint. The job survives closing the reader." : "Use this for localhost or BYO endpoints that only this browser can reach."}</small><label>API base URL<input value={providerConfig.baseUrl} onChange={(event) => { setTtsPreset("custom"); setProviderConfig((current) => ({ ...current, baseUrl: event.target.value })); }} /></label><label>API key<input type="password" value={providerConfig.apiKey} onChange={(event) => setProviderConfig((current) => ({ ...current, apiKey: event.target.value }))} /></label><label>Model<input value={providerConfig.model} onChange={(event) => { setTtsPreset("custom"); setProviderConfig((current) => ({ ...current, model: event.target.value })); }} /></label><label>Voice<input value={providerConfig.voice} onChange={(event) => { setTtsPreset("custom"); setProviderConfig((current) => ({ ...current, voice: event.target.value })); }} /></label><label>Language code<input placeholder="en" value={providerConfig.languageCode || ""} onChange={(event) => { setTtsPreset("custom"); setProviderConfig((current) => ({ ...current, languageCode: event.target.value })); }} /></label></details>
        </section>
        <section className="reader-annotations" aria-label="Bookmarks and notes">
          <header><strong>Bookmarks & notes</strong><span>{annotations.length}</span></header>
          {annotations.filter((annotation) => annotation.chapter_number === chapter.chapter_number).slice(0, 8).map((annotation) => (
            <div className="reader-annotation" key={annotation.id}>
              <button type="button" onClick={() => { if (contentRef.current) contentRef.current.scrollTop = (annotation.percent / 100) * contentRef.current.scrollHeight; }}>{annotation.annotation_type === "bookmark" ? "🔖" : "📝"} {annotation.note || annotation.quote || `At ${Math.round(annotation.percent)}%`}</button>
              <button type="button" onClick={() => void removeAnnotation(annotation.id)} aria-label="Delete annotation">×</button>
            </div>
          ))}
        </section>
      </aside>
    </div>
  );
};

export default Reader;
