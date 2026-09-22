// Central API base URL for the backend (Flask) server.
//
// Local dev  → falls back to the Flask dev server on :5000
// Production → set VITE_API_BASE in the environment (Vercel → Project Settings →
//              Environment Variables) to your deployed backend URL, no trailing
//              slash, e.g. https://mycloset-production-7467.up.railway.app
const _rawBase = import.meta.env.VITE_API_BASE;
if (!_rawBase && import.meta.env.PROD) {
  console.warn("[MyCloset] VITE_API_BASE is not set — all API calls will target http://localhost:5000 and fail in production.");
}
export const API_BASE = _rawBase || "http://localhost:5000";

// Supabase Storage public CDN base for closet images. Loading images straight
// from the CDN — instead of via the API's /static and /icons redirects — removes
// the extra backend hop and lets them load in parallel over HTTP/2. Override the
// project URL with VITE_SUPABASE_URL if it ever changes.
const _SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL || "https://gbtoavsgyzfcwgkftfko.supabase.co").replace(/\/+$/, "");
export const STORAGE_BASE = `${_SUPABASE_URL}/storage/v1/object/public/closet-images`;

const iconName = (icon_path) => icon_path.replace(/\\/g, "/").split("/").pop();

// Direct CDN URL for a generated icon (1024px), from its stored icon_path.
// Use for canvas zones and detail views.
export function iconSrc(icon_path) {
  if (!icon_path) return null;
  return `${STORAGE_BASE}/icons/${encodeURIComponent(iconName(icon_path))}`;
}

// 320px WebP thumb of the same icon — ~10x smaller. Use for grid tiles, rails
// and cards. Pair with onError={fallbackToIcon} for icons made before thumbs.
export function thumbSrc(icon_path) {
  if (!icon_path) return null;
  return `${STORAGE_BASE}/icons/thumb/${encodeURIComponent(iconName(icon_path))}`;
}

// <img onError> handler: swap a missing thumb for the full icon, once.
export function fallbackToIcon(e) {
  const img = e.currentTarget;
  if (img.dataset.fallback) return;
  img.dataset.fallback = "1";
  const full = img.src.replace("/icons/thumb/", "/icons/");
  if (full !== img.src) img.src = full;
}

// Direct CDN URL for an uploaded photo. item.url is "/static/<uid>/<file>".
export function photoSrc(url) {
  if (!url) return null;
  if (/^https?:\/\//.test(url)) return url;
  if (url.startsWith("/static/")) return `${STORAGE_BASE}${url.slice("/static".length)}`;
  return `${API_BASE}${url}`;
}

export default API_BASE;
