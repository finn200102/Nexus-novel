// src/services/libraryService.ts
import apiClient from "./apiClient";
import axios from "axios";

export const libraryService = {
  async getLibraries() {
    try {
      const response = await apiClient.get("/library/");
      return response.data;
    } catch (error) {
      // Don't handle 401 errors here as they're already handled in the interceptor
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching libraries");
      }
      throw error;
    }
  },

  async createLibrary(name: string) {
    try {
      const response = await apiClient.post("/library/", { name });
      return response.data;
    } catch (error) {
      // Don't handle 401 errors here as they're already handled in the interceptor
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error creating library");
      }
      throw error;
    }
  },

  handleError(error: any, message: string) {
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
