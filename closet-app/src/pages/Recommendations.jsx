import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import axios from "axios";
import Layout from "./Layout";
import { API_BASE as API } from "../config";
import "./Recommendations.css";

const EASE = [0.22, 1, 0.36, 1];
const auth = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });
const LS_LOC = "rec_location";

/* Painted top to bottom so a card reads as a person wearing the look rather
   than a row of unrelated products. Widths are relative to the card. */
const STACK = [
  { slot: "hat",          w: 40 },
  { slot: "necklace",     w: 30 },
  { slot: "outer_top",    w: 92 },
  { slot: "inner_top",    w: 78 },
  { slot: "inner_bottom", w: 70 },
  { slot: "outer_bottom", w: 70 },
  { slot: "left_shoe",    w: 52 },
];

/* Location is asked for on demand rather than on load: a permission prompt the
   moment a page opens is the fastest way to get it denied for good. */
function useCoords() {
  const [coords, setCoords] = useState(() => {
    try { return JSON.parse(localStorage.getItem(LS_LOC) || "null"); } catch { return null; }
  });
  const [state, setState] = useState("idle");   // idle | asking | denied

  const ask = useCallback(() => {
    if (!navigator.geolocation) { setState("denied"); return; }
    setState("asking");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = { lat: +pos.coords.latitude.toFixed(3), lon: +pos.coords.longitude.toFixed(3) };
        localStorage.setItem(LS_LOC, JSON.stringify(c));
        setCoords(c); setState("idle");
      },
      () => setState("denied"),
      { timeout: 10000, maximumAge: 15 * 60 * 1000 }
    );
  }, []);

  const clear = useCallback(() => {
    localStorage.removeItem(LS_LOC); setCoords(null); setState("idle");
  }, []);

  return { coords, state, ask, clear };
}

const srcOf = (item) => item?.thumb_url || item?.icon_url || item?.image_url || null;

/* The outfit itself, stacked. */
function OutfitStack({ items, accessories, showAccessories }) {
  const shown = showAccessories ? { ...items, ...accessories } : items;
  const rows = STACK.filter(({ slot }) => shown[slot]);
  return (
    <div className="rec-stack">
      {rows.map(({ slot, w }) => {
        const item = shown[slot];
        const src = srcOf(item);
        return (
          <motion.div
            key={slot}
            className={`rec-stack-row rec-stack-row--${slot}`}
            style={{ width: `${w}%` }}
            layout
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3, ease: EASE }}
            title={item.title || slot}
          >
            {src
              ? <img src={src} alt={item.title || slot} loading="lazy" decoding="async" />
              : <div className="rec-stack-blank" />}
          </motion.div>
        );
      })}
      {/* Wrist and bag pieces sit beside the body rather than in the column. */}
      {showAccessories && (accessories.bag || accessories.bracelet) && (
        <div className="rec-stack-side">
          {["bag", "bracelet"].map((slot) => accessories[slot] && (
            <motion.img
              key={slot}
              src={srcOf(accessories[slot])}
              alt={accessories[slot].title || slot}
              title={accessories[slot].title || slot}
              loading="lazy"
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, ease: EASE }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function OutfitCard({ look, index, onOpen }) {
  const [showAcc, setShowAcc] = useState(false);
  const accessories = look.accessories || {};
  const accCount = Object.keys(accessories).length;

  return (
    <motion.article
      className="rec-card"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: EASE, delay: Math.min(index * 0.05, 0.3) }}
    >
      <OutfitStack items={look.items} accessories={accessories} showAccessories={showAcc} />

      <div className="rec-card-foot">
        <p className="rec-card-reason">{look.reason}</p>
        <div className="rec-card-actions">
          {accCount > 0 && (
            <button
              className={`rec-btn${showAcc ? " rec-btn--on" : ""}`}
              onClick={() => setShowAcc((v) => !v)}
            >
              {showAcc ? "Hide accessories" : `Add accessories (${accCount})`}
            </button>
          )}
          <button className="rec-btn rec-btn--primary" onClick={() => onOpen(look, showAcc)}>
            Open in builder
          </button>
        </div>
      </div>
    </motion.article>
  );
}

export default function Recommendations() {
  const navigate = useNavigate();
  const { coords, state: locState, ask, clear } = useCoords();

  const [weather, setWeather]   = useState(null);
  const [outfits, setOutfits]   = useState([]);
  const [discover, setDiscover] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [discovering, setDiscovering] = useState(true);
  const [discoverErr, setDiscoverErr] = useState(false);

  // The endpoints keep a deep pool per closet and return a slice, so Refresh is
  // a new offset rather than a regeneration -- it comes back from cache.
  const PAGE = 4;
  const [outfitOffset, setOutfitOffset]     = useState(0);
  const [discoverOffset, setDiscoverOffset] = useState(0);
  const [outfitTotal, setOutfitTotal]       = useState(0);
  const [discoverTotal, setDiscoverTotal]   = useState(0);
  // Once a pool is exhausted the next Refresh asks for a new variant, which
  // builds a genuinely different set rather than cycling the same looks.
  const [outfitVariant, setOutfitVariant]     = useState(0);
  const [discoverVariant, setDiscoverVariant] = useState(0);

  // "1-4 of 12" reads as a loop when a new set starts, so say which set it is.
  const pageLabel = (offset, total, variant) =>
    `${variant ? `Set ${variant + 1} · ` : ""}` +
    `${offset + 1}-${Math.min(offset + PAGE, total)} of ${total}`;

  const advance = (offset, total, setOffset, setVariant) => {
    const next = offset + PAGE;
    if (total && next >= total) {
      setVariant((v) => v + 1);
      setOffset(0);
    } else {
      setOffset(next);
    }
  };

  const qs = coords ? `lat=${coords.lat}&lon=${coords.lon}&` : "";

  useEffect(() => {
    let alive = true;
    setLoading(true);
    axios.get(`${API}/suggestions/outfits?${qs}count=${PAGE}&offset=${outfitOffset}&variant=${outfitVariant}`,
              { headers: auth() })
      .then((r) => {
        if (!alive) return;
        setWeather(r.data.weather || null);
        setOutfits(r.data.outfits || []);
        setOutfitTotal(r.data.total || 0);
      })
      .catch(() => { if (alive) setOutfits([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [qs, outfitOffset, outfitVariant]);

  useEffect(() => {
    let alive = true;
    setDiscovering(true);
    axios.get(`${API}/suggestions/discover?${qs}count=${PAGE}&offset=${discoverOffset}&variant=${discoverVariant}`,
              { headers: auth() })
      .then((r) => {
        if (!alive) return;
        setDiscover(r.data.discover || []);
        setDiscoverTotal(r.data.total || 0);
        // The endpoint answers 200 with error:"unavailable" when catalog search
        // cannot run, so an empty list means two different things.
        setDiscoverErr(Boolean(r.data.error));
      })
      .catch(() => { if (alive) { setDiscover([]); setDiscoverErr(true); } })
      .finally(() => { if (alive) setDiscovering(false); });
    return () => { alive = false; };
  }, [qs, discoverOffset, discoverVariant]);

  /* Carry the accessories over only if they are actually on screen, so the
     builder opens with the look the card is showing. */
  const openInBuilder = (look, withAccessories) => {
    const source = withAccessories
      ? { ...look.items, ...(look.accessories || {}) }
      : look.items;
    const suggestion = {};
    for (const [slot, item] of Object.entries(source || {})) {
      if (item?.id) suggestion[slot] = item.id;
    }
    navigate("/outfits", { state: { suggestion } });
  };

  const weatherNote = weather ? ", ranked for the weather where you are" : "";

  return (
    <Layout>
      <div className="rec-page">
        <div className="rec-head">
          <h1 className="page-heading">Recommendations for you</h1>
          <div className="rec-weather">
            {weather ? (
              <>
                <span className="rec-weather-chip">{weather.label}</span>
                <button className="rec-loc-btn" onClick={clear} title="Forget this location">
                  Change
                </button>
              </>
            ) : locState === "denied" ? (
              <span className="rec-weather-note">Location unavailable, showing closet-only picks</span>
            ) : (
              <button className="rec-loc-btn rec-loc-btn--cta" onClick={ask}
                      disabled={locState === "asking"}>
                {locState === "asking" ? "Locating..." : "Use my weather"}
              </button>
            )}
          </div>
        </div>

        {/* From your closet */}
        <section className="rec-section">
          <div className="rec-section-head">
            <div>
              <h2 className="rec-section-title">From your closet</h2>
              <p className="rec-section-sub">
                Complete looks built from pieces you already own{weatherNote}.
              </p>
            </div>
            {outfitTotal > PAGE && (
              <button className="rec-refresh"
                      onClick={() => advance(outfitOffset, outfitTotal, setOutfitOffset, setOutfitVariant)}
                      disabled={loading}>
                Refresh
                <span className="rec-refresh-count">
                  {pageLabel(outfitOffset, outfitTotal, outfitVariant)}
                </span>
              </button>
            )}
          </div>

          {loading ? (
            <div className="rec-grid">
              {[0, 1, 2, 3].map((i) => <div key={i} className="rec-card rec-card--skeleton" />)}
            </div>
          ) : outfits.length === 0 ? (
            <p className="rec-empty">
              Not enough in your closet yet to build a full look. Add a top, a bottom and some shoes.
            </p>
          ) : (
            <div className="rec-grid">
              {outfits.map((look, i) => (
                <OutfitCard key={i} look={look} index={i} onOpen={openInBuilder} />
              ))}
            </div>
          )}
        </section>

        {/* Discover */}
        <section className="rec-section">
          <div className="rec-section-head">
            <div>
              <h2 className="rec-section-title">Discover</h2>
              <p className="rec-section-sub">
                Your looks, with one or two pieces from the catalog that would finish them.
              </p>
            </div>
            {discoverTotal > PAGE && (
              <button className="rec-refresh"
                      onClick={() => advance(discoverOffset, discoverTotal, setDiscoverOffset, setDiscoverVariant)}
                      disabled={discovering}>
                Refresh
                <span className="rec-refresh-count">
                  {pageLabel(discoverOffset, discoverTotal, discoverVariant)}
                </span>
              </button>
            )}
          </div>

          {discovering ? (
            <div className="rec-grid">
              {[0, 1, 2].map((i) => <div key={i} className="rec-card rec-card--skeleton" />)}
            </div>
          ) : discover.length === 0 ? (
            <p className="rec-empty">
              {discoverErr
                ? "Catalog search is still warming up. These will appear once it is ready."
                : "Nothing to complete yet. Add a few more pieces to your closet and check back."}
            </p>
          ) : (
            <div className="rec-grid">
              {discover.map((d, i) => (
                <motion.article
                  key={i}
                  className="rec-card rec-card--discover"
                  initial={{ opacity: 0, y: 18 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.45, ease: EASE, delay: Math.min(i * 0.05, 0.3) }}
                >
                  <OutfitStack items={d.base} accessories={{}} showAccessories={false} />

                  {/* Icons only; the detail rides in on hover so a row of
                      cards stays scannable instead of becoming a price list. */}
                  <div className="rec-adds">
                    <span className="rec-adds-label">Add to finish</span>
                    <div className="rec-adds-row">
                      {d.additions.map((a, k) => (
                        <motion.a
                          key={k}
                          className="rec-add-chip"
                          href={a.item.shop_url || undefined}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => { if (!a.item.shop_url) e.preventDefault(); }}
                          initial={{ opacity: 0, scale: 0.9 }}
                          animate={{ opacity: 1, scale: 1 }}
                          transition={{ duration: 0.3, ease: EASE, delay: 0.05 * k }}
                        >
                          {srcOf(a.item)
                            ? <img src={srcOf(a.item)} alt={a.item.title || ""} loading="lazy" />
                            : <span className="rec-add-blank" />}
                          <span className="rec-add-slot">{a.slot.replace(/_/g, " ")}</span>
                          <span className="rec-add-pop" role="tooltip">
                            <span className="rec-add-pop-title">{a.item.title || "View"}</span>
                            <span className="rec-add-pop-meta">
                              {a.item.brand ? `${a.item.brand} · ` : ""}
                              {a.slot.replace(/_/g, " ")}
                              {a.item.price ? ` · ${a.item.price}` : ""}
                            </span>
                          </span>
                        </motion.a>
                      ))}
                    </div>
                  </div>

                  <div className="rec-card-foot">
                    <p className="rec-card-reason">{d.reason}</p>
                  </div>
                </motion.article>
              ))}
            </div>
          )}
        </section>
      </div>
    </Layout>
  );
}
