import apiClient from "./apiClient";

export interface DemoLibrary {
  library_id: number;
  license: string;
  stories: { novel_id: number; title: string; chapter_number: number; created: boolean }[];
}

export const onboardingService = {
  async addDemo(libraryId: number, signal?: AbortSignal): Promise<DemoLibrary> {
    return (await apiClient.post("/onboarding/demo", { library_id: libraryId }, { signal })).data;
  },
};
