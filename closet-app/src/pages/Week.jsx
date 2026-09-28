import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import axios from "axios";
import Layout from "./Layout";
import { API_BASE as API, iconSrc, thumbSrc } from "../config";
import "./Week.css";

const EASE = [0.22, 1, 0.36, 1];
const auth = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/* Same head-to-foot order the recommendations cards use, so a logged day and a
   suggested look read the same way. */
const STACK = [
  { slot: "hat",          w: 38 },
  { slot: "necklace",     w: 28 },
  { slot: "outer_top",    w: 90 },
  { slot: "inner_top",    w: 76 },
  { slot: "inner_bottom", w: 68 },
  { slot: "outer_bottom", w: 68 },
  { slot: "left_shoe",    w: 50 },
];

const iso = (d) => d.toISOString().slice(0, 10);

function mondayOf(d) {
  const x = new Date(d);
  x.setHours(12, 0, 0, 0);                    // avoid DST edges shifting the day
  const dow = (x.getDay() + 6) % 7;           // Mon = 0
  x.setDate(x.getDate() - dow);
  return x;
}

const srcOf = (it) =>
  it?.thumb_url || it?.icon_url || thumbSrc(it?.icon_path) || iconSrc(it?.icon_path) || null;

function DayStack({ items }) {
  const rows = STACK.filter(({ slot }) => items?.[slot]);
  if (!rows.length) return <div className="wk-stack wk-stack--empty" />;
  return (
    <div className="wk-stack">
      {rows.map(({ slot, w }) => {
        const it = items[slot];
        const src = srcOf(it);
        return (
          <div key={slot} className={`wk-stack-row wk-stack-row--${slot}`} style={{ width: `${w}%` }}>
            {src ? <img src={src} alt={it.title || slot} title={it.title || slot} loading="lazy" />
                 : <div className="wk-stack-blank" />}
          </div>
        );
      })}
    </div>
  );
}

export default function Week() {
  const navigate = useNavigate();
  const [anchor, setAnchor] = useState(() => mondayOf(new Date()));
  const [days, setDays]     = useState([]);
  const [stats, setStats]   = useState(null);
  const [saved, setSaved]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(null);   // which date is choosing an outfit
  const [busy, setBusy]       = useState(false);

  const start = useMemo(() => iso(anchor), [anchor]);
  const todayIso = iso(mondayOf(new Date())) === start ? iso(new Date()) : null;

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      axios.get(`${API}/wear/week?start=${start}`, { headers: auth() }),
      axios.get(`${API}/wear/stats?start=${start}`, { headers: auth() }),
    ])
      .then(([w, s]) => { setDays(w.data.days || []); setStats(s.data || null); })
      .catch(() => { setDays([]); setStats(null); })
      .finally(() => setLoading(false));
  }, [start]);

  useEffect(load, [load]);

  useEffect(() => {
    axios.get(`${API}/outfits`, { headers: auth() })
      .then((r) => setSaved(Array.isArray(r.data) ? r.data : []))
      .catch(() => setSaved([]));
  }, []);

  const logDay = async (date, outfit) => {
    setBusy(true);
    const items = {};
    for (const it of outfit.items || []) {
      if (it.closet_item_id && it.slot) items[it.slot] = it.closet_item_id;
    }
    try {
      await axios.put(`${API}/wear/day/${date}`,
                      { outfit_id: outfit.id, items },
                      { headers: auth() });
      setPicking(null);
      load();
    } catch {
      /* leave the day as it was */
    } finally {
      setBusy(false);
    }
  };

  const clearDay = async (date) => {
    setBusy(true);
    try {
      await axios.delete(`${API}/wear/day/${date}`, { headers: auth() });
      load();
    } catch {
      /* no change */
    } finally {
      setBusy(false);
    }
  };

  const shift = (weeks) => {
    const n = new Date(anchor);
    n.setDate(n.getDate() + weeks * 7);
    setAnchor(mondayOf(n));
  };

  const rangeLabel = () => {
    const end = new Date(anchor);
    end.setDate(end.getDate() + 6);
    const f = (d) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    return `${f(anchor)} – ${f(end)}`;
  };

  return (
    <Layout>
      <div className="wk-page">
        <div className="wk-head">
          <h1 className="page-heading">Outfits of the week</h1>
          <div className="wk-nav">
            <button className="wk-nav-btn" onClick={() => shift(-1)} title="Previous week">‹</button>
            <span className="wk-range">{rangeLabel()}</span>
            <button className="wk-nav-btn" onClick={() => shift(1)} title="Next week">›</button>
            <button className="wk-nav-btn wk-nav-btn--today"
                    onClick={() => setAnchor(mondayOf(new Date()))}>This week</button>
          </div>
        </div>

        {/* Wrapped summary */}
        {stats && (
          <motion.section
            className="wk-wrapped"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: EASE }}
          >
            <div className="wk-stat">
              <span className="wk-stat-n">{stats.days_logged ?? 0}</span>
              <span className="wk-stat-l">days logged</span>
            </div>
            <div className="wk-stat">
              <span className="wk-stat-n">{stats.pieces_worn ?? 0}</span>
              <span className="wk-stat-l">pieces worn</span>
            </div>
            <div className="wk-stat">
              <span className="wk-stat-n">{stats.closet_size ?? 0}</span>
              <span className="wk-stat-l">in your closet</span>
            </div>
            <div className="wk-stat">
              <span className="wk-stat-n">{stats.in_laundry ?? 0}</span>
              <span className="wk-stat-l">in the wash</span>
            </div>

            {stats.top?.length > 0 && (
              <div className="wk-top">
                <span className="wk-top-label">Most worn</span>
                <div className="wk-top-row">
                  {stats.top.map((t) => (
                    <div key={t.id} className="wk-top-item" title={`${t.title} — ${t.times}x`}>
                      {t.thumb_url
                        ? <img src={t.thumb_url} alt={t.title || ""} loading="lazy" />
                        : <span className="wk-top-blank" />}
                      <span className="wk-top-times">{t.times}x</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </motion.section>
        )}

        {/* The seven days */}
        <div className="wk-grid">
          {(loading ? Array.from({ length: 7 }, () => null) : days).map((day, i) => {
            const date = day?.date;
            const isToday = date && date === todayIso;
            const hasItems = day && Object.keys(day.items || {}).length > 0;
            return (
              <motion.div
                key={date || i}
                className={`wk-day${isToday ? " wk-day--today" : ""}${hasItems ? " wk-day--filled" : ""}`}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: EASE, delay: Math.min(i * 0.04, 0.28) }}
              >
                <div className="wk-day-head">
                  <span className="wk-day-name">{DAY_NAMES[i]}</span>
                  {date && (
                    <span className="wk-day-date">
                      {new Date(`${date}T12:00:00`).getDate()}
                    </span>
                  )}
                </div>

                {loading ? (
                  <div className="wk-stack wk-stack--skeleton" />
                ) : hasItems ? (
                  <>
                    <DayStack items={day.items} />
                    <div className="wk-day-foot">
                      <button className="wk-btn" onClick={() => setPicking(date)} disabled={busy}>
                        Change
                      </button>
                      <button className="wk-btn wk-btn--quiet" onClick={() => clearDay(date)} disabled={busy}>
                        Clear
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="wk-stack wk-stack--empty">
                      <span className="wk-empty-mark">+</span>
                    </div>
                    <div className="wk-day-foot">
                      <button className="wk-btn wk-btn--primary"
                              onClick={() => setPicking(date)} disabled={busy}>
                        Log outfit
                      </button>
                    </div>
                  </>
                )}
              </motion.div>
            );
          })}
        </div>

        {/* Outfit picker */}
        <AnimatePresence>
          {picking && (
            <motion.div
              className="wk-picker-backdrop"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={() => setPicking(null)}
            >
              <motion.div
                className="wk-picker"
                initial={{ opacity: 0, y: 20, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 12, scale: 0.98 }}
                transition={{ duration: 0.28, ease: EASE }}
                onClick={(e) => e.stopPropagation()}
              >
                <div className="wk-picker-head">
                  <h2>What did you wear?</h2>
                  <p>{new Date(`${picking}T12:00:00`).toLocaleDateString(undefined,
                      { weekday: "long", month: "long", day: "numeric" })}</p>
                </div>

                {saved.length === 0 ? (
                  <p className="wk-picker-empty">
                    You have not saved any outfits yet. Build one and save it, then log it here.
                  </p>
                ) : (
                  <div className="wk-picker-grid">
                    {saved.map((o) => (
                      <button key={o.id} className="wk-picker-card"
                              onClick={() => logDay(picking, o)} disabled={busy}>
                        <div className="wk-picker-thumbs">
                          {(o.items || []).slice(0, 4).map((it, k) => {
                            const src = thumbSrc(it.icon_path) || iconSrc(it.icon_path);
                            return src
                              ? <img key={k} src={src} alt="" loading="lazy" />
                              : <span key={k} className="wk-picker-blank" />;
                          })}
                        </div>
                        <span className="wk-picker-name">{o.name || "Untitled look"}</span>
                      </button>
                    ))}
                  </div>
                )}

                <div className="wk-picker-foot">
                  <button className="wk-btn wk-btn--quiet" onClick={() => setPicking(null)}>
                    Cancel
                  </button>
                  <button className="wk-btn" onClick={() => navigate("/outfits")}>
                    Build a new one
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Layout>
  );
}
