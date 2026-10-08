import axios from "axios";

/** A request that never got a response: offline, DNS failure, or timeout. */
export const isNetworkError = (error: unknown) => axios.isAxiosError(error) && !error.response;
