import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import axios from "axios";
import Layout from "./Layout";
import { API_BASE as API } from "../config";
import "./Recommendations.css";

const EASE = [0.22, 1, 0.36, 1];
const auth = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });
const LS_LOC = "rec_location";

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

function ItemThumb({ item, size = 74 }) {
  const src = item?.thumb_url || item?.icon_url || item?.image_url;
  if (!src) {
    return <div className="rec-thumb rec-thumb--empty" style={{ width: size, height: size }} />;
  }
  return (
    <img className="rec-thumb" src={src} alt={item.title || ""} loading="lazy"
         style={{ width: size, height: size }} />
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

  const qs = coords ? `lat=${coords.lat}&lon=${coords.lon}&` : "";

  useEffect(() => {
    let alive = true;
    setLoading(true);
    axios.get(`${API}/suggestions/outfits?${qs}count=6`, { headers: auth() })
      .then((r) => {
        if (!alive) return;
        setWeather(r.data.weather || null);
        setOutfits(r.data.outfits || []);
      })
      .catch(() => { if (alive) setOutfits([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [qs]);

  useEffect(() => {
    let alive = true;
    setDiscovering(true);
    axios.get(`${API}/suggestions/discover?${qs}count=4`, { headers: auth() })
      .then((r) => {
        if (!alive) return;
        setDiscover(r.data.discover || []);
        // The backend answers 200 with error:"unavailable" when catalog search
        // cannot run, so an empty list means two different things.
        setDiscoverErr(Boolean(r.data.error));
      })
      .catch(() => { if (alive) { setDiscover([]); setDiscoverErr(true); } })
      .finally(() => { if (alive) setDiscovering(false); });
    return () => { alive = false; };
  }, [qs]);

  const openInBuilder = (look) => {
    const suggestion = {};
    for (const [slot, item] of Object.entries(look.items || {})) {
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
          <h2 className="rec-section-title">From your closet</h2>
          <p className="rec-section-sub">
            Complete looks built from pieces you already own{weatherNote}.
          </p>

          {loading ? (
            <div className="rec-grid">
              {[0, 1, 2].map((i) => <div key={i} className="rec-card rec-card--skeleton" />)}
            </div>
          ) : outfits.length === 0 ? (
            <p className="rec-empty">
              Not enough in your closet yet to build a full look. Add a top, a bottom and some shoes.
            </p>
          ) : (
            <div className="rec-grid">
              {outfits.map((look, i) => (
                <motion.article
                  key={i}
                  className="rec-card"
                  initial={{ opacity: 0, y: 18 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.45, ease: EASE, delay: Math.min(i * 0.05, 0.3) }}
                  onClick={() => openInBuilder(look)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openInBuilder(look); }
                  }}
                >
                  <div className="rec-card-items">
                    {Object.entries(look.items).map(([slot, item]) => (
                      <ItemThumb key={slot} item={item} />
                    ))}
                  </div>
                  <div className="rec-card-foot">
                    <p className="rec-card-reason">{look.reason}</p>
                    <span className="rec-card-open">Open in builder</span>
                  </div>
                </motion.article>
              ))}
            </div>
          )}
        </section>

        {/* Discover */}
        <section className="rec-section">
          <h2 className="rec-section-title">Discover</h2>
          <p className="rec-section-sub">
            Your looks, with one or two pieces from the catalog that would finish them.
          </p>

          {discovering ? (
            <div className="rec-grid">
              {[0, 1].map((i) => <div key={i} className="rec-card rec-card--skeleton" />)}
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
                  <div className="rec-card-items">
                    {Object.entries(d.base).map(([slot, item]) => (
                      <ItemThumb key={slot} item={item} size={58} />
                    ))}
                    <span className="rec-plus">+</span>
                    {d.additions.map((a, k) => (
                      <div key={k} className="rec-add">
                        <ItemThumb item={a.item} size={58} />
                        <span className="rec-add-tag">{a.slot.replace(/_/g, " ")}</span>
                      </div>
                    ))}
                  </div>
                  <div className="rec-card-foot">
                    <p className="rec-card-reason">{d.reason}</p>
                    <div className="rec-add-list">
                      {d.additions.map((a, k) => (
                        <a key={k} className="rec-add-link"
                           href={a.item.shop_url || undefined}
                           target="_blank" rel="noreferrer"
                           onClick={(e) => { if (!a.item.shop_url) e.preventDefault(); }}>
                          {(a.item.title || "View").slice(0, 32)}
                          {a.item.price ? ` - ${a.item.price}` : ""}
                        </a>
                      ))}
                    </div>
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
