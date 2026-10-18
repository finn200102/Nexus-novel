import axios from "axios";

/** Axios errors retain credentials, private bodies and provider query strings. */
export function logRequestFailure(error: unknown, message: string): void {
  if (axios.isCancel(error)) return;
  if (axios.isAxiosError(error)) {
    console.error(message, {status:error.response?.status,code:error.code});
  } else {
    console.error(message);
  }
}
