import apiClient from "./apiClient";
import axios from "axios";
import { dropQueuedProgress, enqueueProgress, installProgressSync, QueuedProgress } from "./progressSyncQueue";
import { isNetworkError } from "./networkErrors";

const sendProgress = (entry: QueuedProgress) => apiClient.put(`/chapter/progress/${entry.novelId}`, {
  chapter_number: entry.chapter,
  position: entry.position,
  percent: entry.percent,
});

export const chapterService = {
  async getChapters(novelId: number) {
    try {
      const response = await apiClient.get(`/chapter/${novelId}`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async downloadChapter(
    library_id: number,
    novelId: number,
    chapterNumber: number
  ) {
    try {
      const response = await apiClient.get(
        `/chapter/download/${library_id}/${novelId}/${chapterNumber}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async downloadChapters(
    library_id: number,
    novelId: number,
    chapterNumbers: number[]
  ) {
    try {
      const downloadPromises = chapterNumbers.map((chapterNumber) =>
        this.downloadChapter(library_id, novelId, chapterNumber)
      );

      return await Promise.all(downloadPromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error downloading chapters");
      }
      throw error;
    }
  },
  async queueChapterDownloads(libraryId: number, novelId: number, count: number) {
    const response = await apiClient.post(`/chapter/queue/${libraryId}/${novelId}`, { count });
    return response.data;
  },

  async getChapterContentByNumber(
    chapterNumber: number,
    libraryId: number,
    novelId: number
  ) {
    try {
      const response = await apiClient.get(
        `/chapter/content/library/${libraryId}/${novelId}/${chapterNumber}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async getReadingProgress(novelId: number) {
    const response = await apiClient.get(`/chapter/progress/${novelId}`);
    return response.data;
  },
  async exportNovelEpub(novelId: number): Promise<Blob> {
    const response = await apiClient.get(`/chapter/novel/${novelId}/export.epub`, { responseType: "blob" });
    return response.data;
  },
  /**
   * Save progress. When the network is down the save is queued locally and
   * sent later (see progressSyncQueue); the call then resolves to null.
   */
  async updateReadingProgress(
    novelId: number,
    chapterNumber: number,
    position: number,
    percent: number
  ) {
    const entry: QueuedProgress = { novelId, chapter: chapterNumber, position, percent, ts: Date.now() };
    try {
      const response = await sendProgress(entry);
      dropQueuedProgress(novelId);
      return response.data;
    } catch (error) {
      if (isNetworkError(error) && enqueueProgress(entry)) return null;
      throw error;
    }
  },
  async getReadingAnnotations(novelId: number) {
    const response = await apiClient.get(`/chapter/annotations/${novelId}`);
    return response.data;
  },
  async getReadingHistory(novelId: number) {
    return (await apiClient.get(`/chapter/history/${novelId}`)).data;
  },
  async getSpoilerSafeRecap(novelId: number) {
    return (await apiClient.get(`/chapter/recap/${novelId}`)).data;
  },
  async createReadingAnnotation(novelId: number, annotation: {
    chapter_number: number;
    annotation_type: "bookmark" | "note" | "highlight";
    position: number;
    percent: number;
    quote?: string;
    note?: string;
  }) {
    const response = await apiClient.post(`/chapter/annotations/${novelId}`, annotation);
    return response.data;
  },
  async deleteReadingAnnotation(annotationId: number) {
    await apiClient.delete(`/chapter/annotations/${annotationId}`);
  },

  async deleteChapterById(chapterId: number) {
    try {
      const response = await apiClient.delete(`/chapter/${chapterId}`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error deleting chapter");
      }
      throw error;
    }
  },
  async deleteChaptersByIds(chapterIds: number[]) {
    try {
      const deletePromises = chapterIds.map((chapterId) =>
        this.deleteChapterById(chapterId)
      );

      return await Promise.all(deletePromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error delete chapters");
      }
      throw error;
    }
  },

  async resetChapterStatus(chapterId: number, status: string) {
    try {
      const response = await apiClient.patch(
        `/chapter/${chapterId}/status?content_status=${status}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error resetting chapter status");
      }
      throw error;
    }
  },

  async getDownloadStatus(novelId: number) {
    try {
      const response = await apiClient.get(`/chapter/novel/${novelId}/download-status`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching download status");
      }
      throw error;
    }
  },

  async cancelChapterDownload(chapterId: number) {
    try {
      const response = await apiClient.delete(`/chapter/${chapterId}/download`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error cancelling chapter download");
      }
      throw error;
    }
  },

  async cancelAllDownloads(novelId: number) {
    try {
      const response = await apiClient.post(`/chapter/novel/${novelId}/cancel-all-downloads`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error cancelling all downloads");
      }
      throw error;
    }
  },

  handleError(error: unknown, message: string) {
    console.error(message + ":", error);

    if (axios.isAxiosError(error)) {
      console.error("Response status:", error.response?.status);
      console.error("Response data:", error.response?.data);
      console.error("Request URL:", error.config?.url);
      console.error("Request method:", error.config?.method);
      console.error("Request headers:", error.config?.headers);
    }
  },
};

// Send saves queued while offline, on start and whenever the network returns.
installProgressSync(sendProgress);
