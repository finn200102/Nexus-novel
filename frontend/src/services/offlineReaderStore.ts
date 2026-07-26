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
const MAX_CACHED_CHAPTERS = 50;

const chapterKey = (novelId: number, chapterNumber: number) => `${novelId}:${chapterNumber}`;

const openDatabase = (): Promise<IDBDatabase> => new Promise((resolve, reject) => {
  const request = indexedDB.open(DATABASE_NAME, 1);
  request.onupgradeneeded = () => {
    const store = request.result.createObjectStore(STORE_NAME, { keyPath: "cache_key" });
    store.createIndex("cached_at", "cached_at");
    store.createIndex("novel_id", "novel_id");
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
