import apiClient from "./apiClient";
import type { ImportJob } from "./liveSearchService";

const readBase64 = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

export const calibreService = {
  /** Queue the stories of a Calibre library's metadata.db as an import job. */
  async importCalibre(libraryId: number, file: File): Promise<ImportJob> {
    const data_base64 = await readBase64(file);
    return (await apiClient.post<ImportJob>("/imports/calibre", { library_id: libraryId, data_base64 }, { timeout: 120000 })).data;
  },

  /** Zip of the user's downloaded EPUBs with Calibre metadata, saved as a file. */
  async downloadExport(): Promise<void> {
    const response = await apiClient.get("/me/export/calibre", { responseType: "blob", timeout: 300000 });
    const url = URL.createObjectURL(response.data as Blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `nexus-calibre-${new Date().toISOString().slice(0, 10)}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },
};
