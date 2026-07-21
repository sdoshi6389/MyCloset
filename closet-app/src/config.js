// Central API base URL for the backend (Flask) server.
//
// Local dev  → falls back to the Flask dev server on :5000
// Production → set VITE_API_BASE in the environment (e.g. Vercel → Project
//              Settings → Environment Variables) to your deployed backend URL,
//              with NO trailing slash, e.g. https://closet-api.up.railway.app
//
// Vite inlines import.meta.env.VITE_* at build time, so this must be set
// BEFORE `vite build` runs on Vercel.
export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:5000";

export default API_BASE;
