export interface OfflineChapter {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
}

interface StoredChapter extends OfflineChapter {
  cache_key: string;
  cached_at: number;
}

const DATABASE_NAME = "nexus-reader";
const STORE_NAME = "chapters";
const AUDIO_STORE_NAME = "chapter_audio";
const AUDIO_JOB_STORE_NAME = "chapter_audio_jobs";
const AUDIO_SEGMENT_STORE_NAME = "chapter_audio_segments";
const MAX_CACHED_CHAPTERS = 50;

const chapterKey = (novelId: number, chapterNumber: number) => `${novelId}:${chapterNumber}`;

const openDatabase = (): Promise<IDBDatabase> => new Promise((resolve, reject) => {
  const request = indexedDB.open(DATABASE_NAME, 3);
  request.onupgradeneeded = () => {
    const database = request.result;
    if (!database.objectStoreNames.contains(STORE_NAME)) {
      const store = database.createObjectStore(STORE_NAME, { keyPath: "cache_key" });
      store.createIndex("cached_at", "cached_at");
      store.createIndex("novel_id", "novel_id");
    }
    if (!database.objectStoreNames.contains(AUDIO_STORE_NAME)) {
      database.createObjectStore(AUDIO_STORE_NAME, { keyPath: "cache_key" });
    }
    if (!database.objectStoreNames.contains(AUDIO_JOB_STORE_NAME)) {
      database.createObjectStore(AUDIO_JOB_STORE_NAME, { keyPath: "cache_key" });
    }
    if (!database.objectStoreNames.contains(AUDIO_SEGMENT_STORE_NAME)) {
      const store = database.createObjectStore(AUDIO_SEGMENT_STORE_NAME, { keyPath: "segment_key" });
      store.createIndex("cache_key", "cache_key");
    }
  };
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});

const withStore = async <T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
  const database = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      const request = work(transaction.objectStore(STORE_NAME));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    database.close();
  }
};

const withAudioStore = async <T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
  const database = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = database.transaction(AUDIO_STORE_NAME, mode);
      const request = work(transaction.objectStore(AUDIO_STORE_NAME));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    database.close();
  }
};

const withNamedStore = async <T>(name: string, mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
  const database = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = database.transaction(name, mode);
      const request = work(transaction.objectStore(name));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    database.close();
  }
};

export type ChapterAudioJobStatus = "queued" | "generating" | "ready" | "failed" | "cancelled";

/**
 * Snapshot the synthesis route at job creation. A resumable job must never
 * silently join chunks produced by two providers or voices.
 */
export interface ChapterAudioProviderSnapshot {
  base_url: string;
  model: string;
  voice: string;
  language_code?: string;
}

export interface ChapterAudioJob {
  cache_key: string;
  novel_id: number;
  chapter_number: number;
  status: ChapterAudioJobStatus;
  chunks: string[];
  completed_chunks: number;
  provider?: ChapterAudioProviderSnapshot;
  error?: string;
  created_at: number;
  updated_at: number;
}

export const offlineReaderStore = {
  async save(chapter: OfflineChapter): Promise<void> {
    if (!("indexedDB" in window)) return;
    await withStore("readwrite", (store) => store.put({
      ...chapter,
      cache_key: chapterKey(chapter.novel_id, chapter.chapter_number),
      cached_at: Date.now(),
    } satisfies StoredChapter));
    await this.evictExcess();
  },

  async get(novelId: number, chapterNumber: number): Promise<OfflineChapter | null> {
    if (!("indexedDB" in window)) return null;
    const value = await withStore<StoredChapter | undefined>("readonly", (store) => store.get(chapterKey(novelId, chapterNumber)));
    if (!value) return null;
    return value;
  },

  async has(novelId: number, chapterNumber: number): Promise<boolean> {
    return Boolean(await this.get(novelId, chapterNumber));
  },

  async countForNovel(novelId: number): Promise<number> {
    if (!("indexedDB" in window)) return 0;
    const database = await openDatabase();
    try {
      return await new Promise<number>((resolve, reject) => {
        const request = database.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).index("novel_id").count(novelId);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    } finally {
      database.close();
    }
  },

  async evictExcess(maximum = MAX_CACHED_CHAPTERS): Promise<void> {
    if (!("indexedDB" in window)) return;
    const database = await openDatabase();
    try {
      await new Promise<void>((resolve, reject) => {
        const transaction = database.transaction(STORE_NAME, "readwrite");
        const store = transaction.objectStore(STORE_NAME);
        const countRequest = store.count();
        countRequest.onsuccess = () => {
          let overflow = Math.max(0, countRequest.result - maximum);
          if (overflow === 0) return;
          const cursorRequest = store.index("cached_at").openCursor();
          cursorRequest.onsuccess = () => {
            const cursor = cursorRequest.result;
            if (!cursor || overflow <= 0) return;
            cursor.delete();
            overflow -= 1;
            cursor.continue();
          };
        };
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      });
    } finally {
      database.close();
    }
  },
};

export const chapterAudioStore = {
  async save(novelId: number, chapterNumber: number, audio: Blob): Promise<void> {
    if (!("indexedDB" in window)) return;
    await withAudioStore("readwrite", (store) => store.put({
      cache_key: chapterKey(novelId, chapterNumber),
      audio,
      created_at: Date.now(),
    }));
  },

  async get(novelId: number, chapterNumber: number): Promise<Blob | null> {
    if (!("indexedDB" in window)) return null;
    const value = await withAudioStore<{ audio?: Blob } | undefined>("readonly", (store) => store.get(chapterKey(novelId, chapterNumber)));
    return value?.audio || null;
  },

  async remove(novelId: number, chapterNumber: number): Promise<void> {
    if (!("indexedDB" in window)) return;
    await withAudioStore("readwrite", (store) => store.delete(chapterKey(novelId, chapterNumber)));
  },
};

const segmentKey = (novelId: number, chapterNumber: number, index: number) => `${chapterKey(novelId, chapterNumber)}:${index}`;

export const chapterAudioJobStore = {
  async get(novelId: number, chapterNumber: number): Promise<ChapterAudioJob | null> {
    if (!("indexedDB" in window)) return null;
    const value = await withNamedStore<ChapterAudioJob | undefined>(AUDIO_JOB_STORE_NAME, "readonly", (store) => store.get(chapterKey(novelId, chapterNumber)));
    return value || null;
  },

  async save(job: ChapterAudioJob): Promise<void> {
    if (!("indexedDB" in window)) return;
    await withNamedStore(AUDIO_JOB_STORE_NAME, "readwrite", (store) => store.put({ ...job, updated_at: Date.now() }));
  },

  async saveSegment(novelId: number, chapterNumber: number, index: number, audio: Blob): Promise<void> {
    if (!("indexedDB" in window)) return;
    await withNamedStore(AUDIO_SEGMENT_STORE_NAME, "readwrite", (store) => store.put({
      segment_key: segmentKey(novelId, chapterNumber, index),
      cache_key: chapterKey(novelId, chapterNumber),
      index,
      audio,
    }));
  },

  async segments(novelId: number, chapterNumber: number): Promise<Blob[]> {
    if (!("indexedDB" in window)) return [];
    const database = await openDatabase();
    try {
      return await new Promise<Blob[]>((resolve, reject) => {
        const request = database.transaction(AUDIO_SEGMENT_STORE_NAME, "readonly")
          .objectStore(AUDIO_SEGMENT_STORE_NAME).index("cache_key").getAll(chapterKey(novelId, chapterNumber));
        request.onsuccess = () => resolve((request.result as Array<{ index: number; audio: Blob }>)
          .sort((left, right) => left.index - right.index).map((segment) => segment.audio));
        request.onerror = () => reject(request.error);
      });
    } finally {
      database.close();
    }
  },

  async clearSegments(novelId: number, chapterNumber: number): Promise<void> {
    if (!("indexedDB" in window)) return;
    const database = await openDatabase();
    try {
      await new Promise<void>((resolve, reject) => {
        const transaction = database.transaction(AUDIO_SEGMENT_STORE_NAME, "readwrite");
        const index = transaction.objectStore(AUDIO_SEGMENT_STORE_NAME).index("cache_key");
        const request = index.openCursor(IDBKeyRange.only(chapterKey(novelId, chapterNumber)));
        request.onsuccess = () => {
          const cursor = request.result;
          if (cursor) { cursor.delete(); cursor.continue(); }
        };
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      });
    } finally {
      database.close();
    }
  },

  async remove(novelId: number, chapterNumber: number): Promise<void> {
    if (!("indexedDB" in window)) return;
    await this.clearSegments(novelId, chapterNumber);
    await withNamedStore(AUDIO_JOB_STORE_NAME, "readwrite", (store) => store.delete(chapterKey(novelId, chapterNumber)));
  },
};
