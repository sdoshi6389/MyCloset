/**
 * Registers global axios interceptors for automatic JWT refresh.
 * Import this file once in main.jsx — all axios calls across the app
 * then benefit without needing to change existing page imports.
 *
 * On any 401 response the interceptor does a single silent POST /refresh.
 * If successful, the original request is retried with the new token.
 * If the refresh itself fails, the user is redirected to login.
 */
import axios from "axios";
import { API_BASE } from "./config";

// Separate raw instance for refresh calls — does NOT go through the interceptor,
// preventing an infinite retry loop.
const _raw = axios.create({ baseURL: API_BASE });

let _refreshing = null; // coalesce parallel 401s into one refresh request

async function doRefresh() {
  const token = localStorage.getItem("token");
  if (!token) throw new Error("no token");
  const res = await _raw.post(
    "/refresh",
    {},
    { headers: { Authorization: `Bearer ${token}` } },
  );
  localStorage.setItem("token", res.data.token);
  if (res.data.user_id != null) localStorage.setItem("userId", String(res.data.user_id));
  if (res.data.email) localStorage.setItem("userEmail", res.data.email);
  return res.data.token;
}

// Response interceptor on the default global axios instance
axios.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config;
    if (err.response?.status === 401 && !original._retried) {
      original._retried = true;
      try {
        if (!_refreshing) {
          _refreshing = doRefresh().finally(() => { _refreshing = null; });
        }
        const newToken = await _refreshing;
        original.headers = { ...original.headers, Authorization: `Bearer ${newToken}` };
        return axios(original);
      } catch {
        localStorage.removeItem("token");
        localStorage.removeItem("userId");
        localStorage.removeItem("userEmail");
        window.location.replace("/?expired=1");
        return Promise.reject(err);
      }
    }
    return Promise.reject(err);
  },
);
