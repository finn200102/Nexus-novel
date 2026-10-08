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
  /** Saved explicitly by "Make available offline"; never evicted automatically. */
  pinned?: boolean;
}

export interface OfflineChapterSummary {
  novel_id: number;
  chapter_number: number;
  title: string;
  pinned: boolean;
  cached_at: number;
  size_bytes: number;
}

const encoder = new TextEncoder();
/** Approximate stored size: UTF-8 bytes of the text payload. */
const chapterSizeBytes = (chapter: Pick<OfflineChapter, "title" | "content">) =>
  encoder.encode(chapter.title + chapter.content).length;

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

const runStoreTransaction = async (mode: IDBTransactionMode, work: (store: IDBObjectStore) => void): Promise<void> => {
  const database = await openDatabase();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      work(transaction.objectStore(STORE_NAME));
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
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
  /**
   * Store a chapter. A re-save keeps the existing pinned flag unless
   * `options.pinned` is given, so opening a pinned chapter never unpins it.
   */
  async save(chapter: OfflineChapter, options: { pinned?: boolean } = {}): Promise<void> {
    if (!("indexedDB" in window)) return;
    const key = chapterKey(chapter.novel_id, chapter.chapter_number);
    await runStoreTransaction("readwrite", (store) => {
      const existing = store.get(key);
      existing.onsuccess = () => {
        const previous = existing.result as StoredChapter | undefined;
        store.put({
          ...chapter,
          cache_key: key,
          cached_at: Date.now(),
          pinned: options.pinned ?? previous?.pinned ?? false,
        } satisfies StoredChapter);
      };
    });
    await this.evictExcess();
  },

  /** Every stored chapter of one novel, in chapter order, with its size. */
  async listForNovel(novelId: number): Promise<OfflineChapterSummary[]> {
    if (!("indexedDB" in window)) return [];
    const records = await withStore<StoredChapter[]>("readonly", (store) => store.index("novel_id").getAll(novelId));
    return records
      .map((record) => ({
        novel_id: record.novel_id,
        chapter_number: record.chapter_number,
        title: record.title,
        pinned: Boolean(record.pinned),
        cached_at: record.cached_at,
        size_bytes: chapterSizeBytes(record),
      }))
      .sort((left, right) => left.chapter_number - right.chapter_number);
  },

  /** Delete every stored chapter of one novel, pinned or not. Returns the count removed. */
  async removeForNovel(novelId: number): Promise<number> {
    if (!("indexedDB" in window)) return 0;
    let removed = 0;
    await runStoreTransaction("readwrite", (store) => {
      const request = store.index("novel_id").openCursor(IDBKeyRange.only(novelId));
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return;
        cursor.delete();
        removed += 1;
        cursor.continue();
      };
    });
    return removed;
  },

  /** Keep at most `maximum` chapters by evicting the oldest unpinned ones. Pinned chapters are never evicted, so they may exceed the limit. */
  async evictExcess(maximum = MAX_CACHED_CHAPTERS): Promise<void> {
    if (!("indexedDB" in window)) return;
    await runStoreTransaction("readwrite", (store) => {
      const countRequest = store.count();
      countRequest.onsuccess = () => {
        let overflow = Math.max(0, countRequest.result - maximum);
        if (overflow === 0) return;
        const cursorRequest = store.index("cached_at").openCursor();
        cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result;
          if (!cursor || overflow <= 0) return;
          if (!(cursor.value as StoredChapter).pinned) {
            cursor.delete();
            overflow -= 1;
          }
          cursor.continue();
        };
      };
    });
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
