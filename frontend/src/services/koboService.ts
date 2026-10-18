import type { KoboBookVersion as GeneratedBookVersion, KoboBookVersionPage as GeneratedBookVersionPage, KoboVersionConfirmation as GeneratedConfirmation, KoboVersionConfirmed } from "../generated/api";
import apiClient from "./apiClient";

export type KoboDevice = {
  id: number;
  label: string;
  shelf_id: number | null;
  shelf_name: string | null;
  created_at: string | null;
  last_used_at: string | null;
  last_sync_at: string | null;
};

export type KoboDeviceList = {
  /** Whether the server can convert books to KEPUB (kepubify installed). */
  kepub: boolean;
  devices: KoboDevice[];
};

export type CreatedKoboDevice = KoboDevice & {
  /** Returned once; the server keeps only a hash. */
  token: string;
  endpoint_path: string;
};

export type KoboBookVersion = GeneratedBookVersion;
export type KoboBookVersionPage = GeneratedBookVersionPage;
export type KoboVersionConfirmation = GeneratedConfirmation;

export const koboService = {
  books: async (deviceId: number, offset = 0) =>
    (await apiClient.get<KoboBookVersionPage>(`/kobo-devices/${deviceId}/books`, { params: { offset, limit: 50 } })).data,
  confirmVersion: async (deviceId: number, entitlement: string, input: KoboVersionConfirmation) =>
    (await apiClient.post<KoboVersionConfirmed>(`/kobo-devices/${deviceId}/books/${encodeURIComponent(entitlement)}/confirm-version`, input)).data,
  list: async () => (await apiClient.get<KoboDeviceList>("/kobo-devices")).data,
  create: async (label: string, shelfId: number | null) =>
    (await apiClient.post<CreatedKoboDevice>("/kobo-devices", { label, shelf_id: shelfId })).data,
  setShelf: async (id: number, shelfId: number) =>
    (await apiClient.patch<KoboDevice>(`/kobo-devices/${id}`, { shelf_id: shelfId })).data,
  revoke: async (id: number) => {
    await apiClient.delete(`/kobo-devices/${id}`);
  },
};

/** The line for Kobo eReader.conf; the API lives under /api behind the bundled web server. */
export const koboEndpointLine = (endpointPath: string, origin = window.location.origin) =>
  `api_endpoint=${origin}/api${endpointPath}`;
