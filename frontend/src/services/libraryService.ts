// libraryService.ts
import axios from "axios";

interface LibrarySchema {
  id: number;
  name: string;
  user_id: number;
}

class LibraryService {
  // Helper method to get authentication headers
  private getAuthHeaders() {
    const token = localStorage.getItem("token");

    if (!token) {
      console.warn("No authentication token found in localStorage");
      return { headers: {} };
    }

    // Log the exact header being sent
    const authHeader = `Bearer ${token}`;
    console.log("Authorization header:", authHeader);

    return {
      headers: {
        Authorization: authHeader,
      },
    };
  }

  async getAllLibraries(): Promise<LibrarySchema[]> {
    try {
      // Log the full request details
      console.log("Making GET request to /api/library");
      console.log("With headers:", this.getAuthHeaders());

      const response = await axios.get<LibrarySchema[]>(
        "/api/library",
        this.getAuthHeaders()
      );

      console.log("Libraries response:", response.data);
      return response.data;
    } catch (error) {
      console.error("Error fetching libraries:", error);
      this.handleError(error);
      throw error;
    }
  }

  async createLibrary(name: string): Promise<LibrarySchema> {
    try {
      console.log("Creating library with name:", name);

      // Only send the name
      const libraryData = { name };

      // Log the full request details
      console.log("Making POST request to /api/library");
      console.log("With data:", libraryData);
      console.log("With headers:", this.getAuthHeaders());

      // Make the request with explicit headers
      const token = localStorage.getItem("token");
      if (!token) {
        throw new Error("No authentication token found");
      }

      const response = await axios({
        method: "post",
        url: "/api/library",
        data: libraryData,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      });

      console.log("Library created:", response.data);
      return response.data;
    } catch (error) {
      console.error("Error creating library:", error);
      this.handleError(error);
      throw error;
    }
  }

  // Helper method to handle errors
  private handleError(error: any) {
    if (axios.isAxiosError(error)) {
      console.error("Response status:", error.response?.status);
      console.error("Response data:", error.response?.data);

      // Check request details
      console.error("Request URL:", error.config?.url);
      console.error("Request method:", error.config?.method);
      console.error("Request headers:", error.config?.headers);

      // Check for authentication errors
      if (error.response?.status === 401) {
        console.error("Authentication error - token may be invalid");

        // Log the current token
        const token = localStorage.getItem("token");
        console.log("Current token:", token);

        // Try to refresh the page or redirect to login
        alert("Your session has expired. Please log in again.");
      }
    }
  }
}

// Export a singleton instance
export const libraryService = new LibraryService();
