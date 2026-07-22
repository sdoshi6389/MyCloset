// Central API base URL for the backend (Flask) server.
//
// Local dev  → falls back to the Flask dev server on :5000
// Production → set VITE_API_BASE in the environment (Vercel → Project Settings →
//              Environment Variables) to your deployed backend URL, no trailing
//              slash, e.g. https://mycloset-production-7467.up.railway.app
export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:5000";

// Supabase Storage public CDN base for closet images. Loading images straight
// from the CDN — instead of via the API's /static and /icons redirects — removes
// the extra backend hop and lets them load in parallel over HTTP/2. Override the
// project URL with VITE_SUPABASE_URL if it ever changes.
const _SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL || "https://gbtoavsgyzfcwgkftfko.supabase.co").replace(/\/+$/, "");
export const STORAGE_BASE = `${_SUPABASE_URL}/storage/v1/object/public/closet-images`;

// Direct CDN URL for a generated icon, from its stored icon_path.
export function iconSrc(icon_path) {
  if (!icon_path) return null;
  const name = icon_path.replace(/\\/g, "/").split("/").pop();
  return `${STORAGE_BASE}/icons/${encodeURIComponent(name)}`;
}

// Direct CDN URL for an uploaded photo. item.url is "/static/<uid>/<file>".
export function photoSrc(url) {
  if (!url) return null;
  if (/^https?:\/\//.test(url)) return url;
  if (url.startsWith("/static/")) return `${STORAGE_BASE}${url.slice("/static".length)}`;
  return `${API_BASE}${url}`;
}

export default API_BASE;
