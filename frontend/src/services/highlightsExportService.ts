import apiClient from "./apiClient";

export interface ReadwiseStatus {
  connected: boolean;
}

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

const today = () => new Date().toISOString().slice(0, 10);

export const highlightsExportService = {
  /** One Markdown file per story, zipped. */
  async downloadLibraryZip(): Promise<void> {
    const response = await apiClient.get("/export/highlights", { params: { format: "markdown" }, responseType: "blob" });
    saveBlob(response.data, `nexus-highlights-${today()}.zip`);
  },

  /** Markdown notes for a single story. */
  async downloadStoryNotes(novelId: number, title: string): Promise<void> {
    const response = await apiClient.get("/export/highlights", {
      params: { format: "markdown", novel_id: novelId },
      responseType: "blob",
    });
    const base = title.replace(/[\\/:*?"<>|#^[\]]+/g, " ").replace(/\s+/g, " ").trim() || "story";
    saveBlob(response.data, `${base}.md`);
  },

  async readwiseStatus(): Promise<ReadwiseStatus> {
    return (await apiClient.get("/export/readwise")).data;
  },

  async connectReadwise(token: string): Promise<ReadwiseStatus> {
    return (await apiClient.put("/export/readwise", { token })).data;
  },

  async disconnectReadwise(): Promise<void> {
    await apiClient.delete("/export/readwise");
  },

  async syncReadwise(): Promise<{ exported: number }> {
    return (await apiClient.post("/export/readwise/sync", {})).data;
  },
};
