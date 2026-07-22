import React, { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import Layout from "./Layout";
import { useCircle } from "../context/CircleContext";
import "./Builder.css";

import { API_BASE, iconSrc } from "../config";

// ── Zone definitions ──────────────────────────────────────────────────────────
// Bracelet zones are intentionally excluded from ZONES — they live in
// BRACELET_ZONE_DEF and are rendered by BraceletStack components so they can
// grow dynamically as items are stacked.
const ZONES = [
  // ── FRONT ─────────────────────────────────────────────────────────────────────
  { face: "front", id: "hat",          label: "Hat",       top:   0, left:  92, width: 116, height:  60, z: 9, recede: 1.00 },
  { face: "front", id: "necklace",     label: "Necklace",  top:  60, left: 108, width:  84, height:  38, z: 7, recede: 1.00 },
  { face: "front", id: "outer_top",    label: "Jacket",    top:  98, left:   4, width: 292, height: 130, z: 6, recede: 1.00 },
  { face: "front", id: "inner_top",    label: "Shirt",     top: 228, left:  22, width: 256, height: 120, z: 4, recede: 0.93 },
  { face: "front", id: "inner_bottom", label: "Pants",     top: 348, left:  22, width: 256, height: 130, z: 3, recede: 0.90 },
  { face: "front", id: "outer_bottom", label: "Skirt",     top: 348, left:  28, width: 244, height: 106, z: 5, recede: 0.97 },
  { face: "front", id: "bag",          label: "Bag",       top: 350, left: 234, width:  66, height:  90, z: 7, recede: 1.00 },
  { face: "front", id: "left_shoe",    label: "L Shoe",    top: 458, left:   8, width: 126, height:  62, z: 4, recede: 0.90 },
  { face: "front", id: "right_shoe",   label: "R Shoe",    top: 458, left: 166, width: 126, height:  62, z: 4, recede: 0.90 },
  { face: "front", id: "left_sock",    label: "L Sock",    top: 466, left:  16, width: 106, height:  54, z: 2, recede: 0.82 },
  { face: "front", id: "right_sock",   label: "R Sock",    top: 466, left: 174, width: 106, height:  54, z: 2, recede: 0.82 },
  // ── BACK (underlayers — revealed when canvas is flipped) ─────────────────────
  { face: "back",  id: "innerwear",    label: "Innerwear", top: 228, left:  22, width: 256, height: 120, z: 4, recede: 1.00 },
  { face: "back",  id: "underwear",    label: "Underwear", top: 348, left:  44, width: 212, height: 130, z: 4, recede: 1.00 },
];

// Bracelet stacks: left arm (canvas-left) and right arm (canvas-right).
// top is computed at render time from computeZoneTops["bracelet_left/right"].
const BRACELET_ZONE_DEF = {
  left:  { id: "bracelet_left",  label: "L Bracelet", left:   4, width: 46, z: 8, recede: 1.00 },
  right: { id: "bracelet_right", label: "R Bracelet", left: 250, width: 46, z: 8, recede: 1.00 },
};

// ── Zone inference ─────────────────────────────────────────────────────────────
function inferZone(item) {
  const text = [item.title, item.type, item.caption, item.category, item.subcategory]
    .filter(Boolean).join(" ").toLowerCase();

  if (/\b(hat|cap|beanie|beret|visor|snapback|fedora|bucket hat|trucker|toboggan|baseball cap)\b/.test(text)) return "hat";
  if (/\b(glasses|sunglasses|shades|eyewear|frames|specs)\b/.test(text)) return "hat";
  if (/\b(necklace|chain|choker|pendant|locket|collar chain)\b/.test(text)) return "necklace";
  if (/\b(scarf|bandana)\b/.test(text)) return "necklace";
  // Bracelets default to left arm; user can drag to right arm drop zone
  if (/\b(bracelet|bangle|cuff|watch|wristband|wristwatch|arm candy)\b/.test(text)) return "bracelet_left";
  if (/\b(bag|purse|handbag|clutch|backpack|tote|satchel|crossbody|fanny pack|shoulder bag|mini bag)\b/.test(text)) return "bag";

  // Bottoms and shoes checked BEFORE outer_top so that product names like
  // "Varsity Shorts", "Bomber Shorts", "Trench Shorts", "Anorak Short" etc.
  // don't get mis-routed to the jacket zone.
  if (/\b(skirt|shorts|mini|midi|maxi|culottes)\b/.test(text)) return "outer_bottom";
  if (/\b(pants|jeans|trousers|chinos|slacks|leggings?|joggers?|sweatpants?|cargo|denim)\b/.test(text)
      && !/\bshorts\b/.test(text)) return "inner_bottom";
  if (/\b(shoe|sneaker|boot|loafer|sandal|heel|flat|pump|oxford|mule|slipper|clog|kicks)\b/.test(text)) return "left_shoe";
  if (/\b(sock|stocking|tight|anklet)\b/.test(text)) return "left_sock";

  if (/\b(jacket|coat|blazer|puffer|windbreaker|anorak|trench|parka|overcoat|raincoat|bomber|denim jacket|leather jacket|varsity)\b/.test(text)) return "outer_top";
  if (/\b(hoodie|zip.?up|fleece)\b/.test(text) && !/\bshirt\b/.test(text)) return "outer_top";
  if (/\b(bralette|sports.?bra|camisole|cami|undershirt|base.?layer|thermal|bodysuit|lingerie|tank.?undershirt)\b/.test(text)) return "innerwear";
  if (/\b(bra)\b/.test(text) && !/\b(bracelet|bangle)\b/.test(text)) return "innerwear";
  if (/\btank\b/.test(text) && /\b(under|inner)\b/.test(text)) return "innerwear";
  if (/\b(boxers|briefs|boxer.?briefs|underwear)\b/.test(text)) return "underwear";
  if (/\b(shirt|tee|t-shirt|blouse|knit|sweater|pullover|sweatshirt|jersey|crop|cardigan|polo|tank|tube top)\b/.test(text)
      && !/\b(coat|trench|jacket|parka|puffer|overcoat)\b/.test(text)) return "inner_top";
  if (/\bhoodi(e|es)\b/.test(text)) return "inner_top";
  if (/\btop\b/.test(text) && !/(jacket|coat|outer)/.test(text)) return "inner_top";

  const t = (item.type || "").toLowerCase();
  const c = (item.category || "").toLowerCase();
  if (t === "outerwear" || c === "outerwear") return "outer_top";
  if (t === "top"       || c === "top"  || c === "tops")     return "inner_top";
  if (t === "bottom"    || c === "bottom" || c === "bottoms") return "inner_bottom";
  if (/shoe|footwear/.test(t) || /shoe|footwear/.test(c)) return "left_shoe";
  if (/hat|headwear/.test(t)  || /hat|headwear/.test(c))  return "hat";
  if (/accessory/.test(t)     || /accessory/.test(c))     return "necklace";
  if (c === "innerwear") return "innerwear";
  if (c === "underwear") return "underwear";

  return null;
}

const ZONE_SHORT = {
  hat:           "Hat",
  necklace:      "Necklace",
  outer_top:     "Jacket",
  inner_top:     "Top",
  innerwear:     "Innerwear",
  underwear:     "Underwear",
  bracelet_left: "Bracelet",
  bracelet_right:"Bracelet",
  inner_bottom:  "Pants",
  outer_bottom:  "Skirt",
  bag:           "Bag",
  left_shoe:     "Shoes",
  right_shoe:    "Shoes",
  left_sock:     "Socks",
  right_sock:    "Socks",
};

const SLOT_TO_CATEGORY = {
  inner_top:     "Tops",
  inner_bottom:  "Bottoms",
  outer_top:     "Outerwear",
  outer_bottom:  "Bottoms",
  left_shoe:     "Shoes",
  right_shoe:    "Shoes",
  hat:           "Accessories",
  bag:           "Accessories",
  necklace:      "Accessories",
  bracelet_left: "Accessories",
  bracelet_right:"Accessories",
  innerwear:     "Innerwear",
  underwear:     "Innerwear",
};

const abs  = (p) => (!p ? null : p.startsWith("http") ? p : `${API_BASE}${p}`);
const tok  = () => localStorage.getItem("token");
const auth = () => ({ Authorization: `Bearer ${tok()}` });

const iconUrl = (icon_path) => iconSrc(icon_path);

const SLOT_PICKER = [
  { id: "hat",           label: "Hat"       },
  { id: "necklace",      label: "Necklace"  },
  { id: "outer_top",     label: "Jacket"    },
  { id: "inner_top",     label: "Top"       },
  { id: "bracelet_left", label: "Bracelet"  },
  { id: "bag",           label: "Bag"       },
  { id: "inner_bottom",  label: "Pants"     },
  { id: "shorts",        label: "Shorts"    },
  { id: "outer_bottom",  label: "Skirt"     },
  { id: "left_shoe",     label: "Shoes"     },
  { id: "left_sock",     label: "Socks"     },
  { id: "innerwear",     label: "Innerwear" },
  { id: "underwear",     label: "Underwear" },
];

// "shorts" recs are placed into the outer_bottom canvas zone (same visual slot as skirts)
const REC_SLOT_TO_ZONE = { shorts: "outer_bottom" };

// ── Editorial computation ─────────────────────────────────────────────────────
function computeEditorial(outfit) {
  const filled = Object.values(outfit).filter(Boolean);
  if (!filled.length) return null;

  const split = (s) => (s || "").split(",").map((v) => v.trim()).filter(Boolean);
  const capitalize = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  const vibes    = [...new Set(filled.flatMap((i) => split(i.vibe)))];
  const styles   = [...new Set(filled.flatMap((i) => split(i.style)))];
  const occasions = [...new Set(filled.flatMap((i) => split(i.occasion)))];
  const seasons  = [...new Set(filled.flatMap((i) => split(i.season)))];

  const scores = filled
    .map((i) => i.formality_score)
    .filter((n) => typeof n === "number" && !isNaN(n));
  const formalityAvg = scores.length
    ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
    : null;

  const nameTokens = [...new Set([...vibes.slice(0, 2), ...styles.slice(0, 1)])];
  const outfitName = nameTokens.length
    ? nameTokens.map(capitalize).join(" ") + " Look"
    : "Untitled Look";

  const moodMap = {
    casual:     "Effortless ease for everyday moments.",
    formal:     "Polished precision for distinguished occasions.",
    streetwear: "Urban energy, cultural confidence.",
    minimalist: "Less, but always intentional.",
    romantic:   "Soft power in every silhouette.",
    athletic:   "Where form meets function.",
    bohemian:   "Free spirit, grounded style.",
    preppy:     "Classic references with a modern edge.",
    luxe:       "Refined comfort, quiet statement.",
    edgy:       "Deliberate contrast, controlled tension.",
    cool:       "Understated confidence.",
    elegant:    "Grace in the details.",
  };

  const mood =
    [...styles, ...vibes]
      .map((k) => moodMap[k.toLowerCase()])
      .find(Boolean) || "A look with its own vocabulary.";

  return { outfitName, mood, occasions, seasons, formalityAvg, vibes, styles };
}

// ── Builder ───────────────────────────────────────────────────────────────────
export default function Builder() {
  const [items, setItems]       = useState([]);
  const [outfit, setOutfit]     = useState(() =>
    Object.fromEntries(ZONES.map((z) => [z.id, null]))
  );
  // One bracelet per wrist: { left: item|null, right: item|null }
  const [braceletStacks, setBraceletStacks] = useState({ left: null, right: null });
  // Nudge position map: zoneId → { x, y }. Written by child components; read on save.
  const nudgeOffsetMapRef = useRef({});
  const [loadedNudges, setLoadedNudges] = useState({});
  const [nudgeKey, setNudgeKey]         = useState(0);

  const [hovered, setHovered]       = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragZone, setDragZone]     = useState(null);
  const [altHeld, setAltHeld]       = useState(false);
  const [savedOutfits, setSavedOutfits] = useState([]);

  const [flipped, setFlipped]     = useState(false);

  const [recommenderOn, setRecommenderOn] = useState(false);
  const [catalogMode,   setCatalogMode]   = useState(false);
  const [recGender,     setRecGender]     = useState("male");
  const [activeRecSlot, setActiveRecSlot] = useState(null);
  const [recs,          setRecs]          = useState({});
  const [recsLoading,   setRecsLoading]   = useState(false);
  const [recCardIndex,  setRecCardIndex]  = useState({});
  const [previews,      setPreviews]      = useState({});

  const [devMode, setDevMode]     = useState(false);
  const [saveModal, setSaveModal] = useState(false);
  const [saveName, setSaveName]   = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [saving, setSaving]       = useState(false);

  const pageRef    = useRef(null);
  const recFetchRef = useRef(null);
  const { circles, activeCircle, setActiveCircle } = useCircle();

  // ── Fetch closet items ────────────────────────────────────────────────────
  useEffect(() => {
    const params = activeCircle ? `?circle_id=${activeCircle.id}` : "";
    axios
      .get(`${API_BASE}/builder/get_closet_icons${params}`, { headers: auth() })
      .then((res) => {
        const data = Array.isArray(res.data) ? res.data : [res.data];
        setItems(
          data.filter(Boolean).map((it) => ({
            ...it,
            icon_url:  abs(it.icon_url),
            image_url: abs(it.image_url),
          }))
        );
      })
      .catch(console.error);
  }, [activeCircle]);

  const fetchSaved = useCallback(() => {
    const params = activeCircle ? `?circle_id=${activeCircle.id}` : "";
    axios
      .get(`${API_BASE}/outfits${params}`, { headers: auth() })
      .then((res) => setSavedOutfits(Array.isArray(res.data) ? res.data : []))
      .catch(console.error);
  }, [activeCircle]);

  useEffect(() => { fetchSaved(); }, [fetchSaved]);

  // ── Alt key — layer explosion ─────────────────────────────────────────────
  useEffect(() => {
    const onDown = (e) => { if (e.key === "Alt") { e.preventDefault(); setAltHeld(true); } };
    const onUp   = (e) => { if (e.key === "Alt") setAltHeld(false); };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup",   onUp);
    return () => { window.removeEventListener("keydown", onDown); window.removeEventListener("keyup", onUp); };
  }, []);

  // ── Recommendation fetch ──────────────────────────────────────────────────
  useEffect(() => {
    if (!recommenderOn) { setActiveRecSlot(null); setRecs({}); setPreviews({}); }
  }, [recommenderOn]);

  useEffect(() => {
    const canvasZone = REC_SLOT_TO_ZONE[activeRecSlot] || activeRecSlot;
    if (activeRecSlot && outfit[canvasZone]) {
      setActiveRecSlot(null);
      setRecs({});
      setPreviews({});
    }
  }, [outfit, activeRecSlot]);

  useEffect(() => {
    if (!recommenderOn || !activeRecSlot) { setRecs({}); setPreviews({}); return; }
    if (!Object.values(outfit).some(Boolean)) { setRecs({}); setPreviews({}); return; }
    const _recZone = REC_SLOT_TO_ZONE[activeRecSlot] || activeRecSlot;
    if (outfit[_recZone]) { setRecs({}); setPreviews({}); return; }

    const fillSlots = [activeRecSlot];

    clearTimeout(recFetchRef.current);
    recFetchRef.current = setTimeout(() => {
      setRecsLoading(true);
      const outfitPayload = {};
      for (const [slot, item] of Object.entries(outfit)) {
        outfitPayload[slot] = item ? {
          id: item.id, color: item.color, vibe: item.vibe, style: item.style,
          formality_score: item.formality_score, category: item.category, type: item.type,
        } : null;
      }
      axios.post(`${API_BASE}/recommend`, {
        outfit: outfitPayload, fill_slots: fillSlots,
        mode: catalogMode ? "catalog" : "closet", top_k: 5,
        gender: recGender,
      }, { headers: { ...auth(), "Content-Type": "application/json" } })
        .then((res) => {
          const raw = res.data.recommendations || {};
          const processed = {};
          for (const [slot, candidates] of Object.entries(raw)) {
            // Remap virtual rec slots to their canvas zone so the ghost + previews work
            const zoneKey = REC_SLOT_TO_ZONE[slot] || slot;
            processed[zoneKey] = candidates.map((c) => ({
              ...c, icon_url: abs(c.icon_url), image_url: abs(c.image_url),
            }));
          }
          setRecs(processed);
          setRecCardIndex({});
          setPreviews({});
        })
        .catch((e) => { console.error("Recommend error:", e); setRecs({}); })
        .finally(() => setRecsLoading(false));
    }, 800);

    return () => clearTimeout(recFetchRef.current);
  }, [recommenderOn, catalogMode, recGender, outfit, activeRecSlot]);

  // ── Outfit helpers ────────────────────────────────────────────────────────
  const removeSlot  = (id) => setOutfit((p) => ({ ...p, [id]: null }));

  const removeBracelet = useCallback((side) => {
    setBraceletStacks((prev) => ({ ...prev, [side]: null }));
  }, []);

  const resetOutfit = () => {
    setOutfit(Object.fromEntries(ZONES.map((z) => [z.id, null])));
    setBraceletStacks({ left: null, right: null });
    nudgeOffsetMapRef.current = {};
    setLoadedNudges({});
    setNudgeKey((k) => k + 1);
  };

  const filledCount = Object.values(outfit).filter(Boolean).length
    + (braceletStacks.left ? 1 : 0) + (braceletStacks.right ? 1 : 0);

  const hasRecs = Object.values(recs).some((arr) => arr.length > 0);

  // Drop handler — bracelets go to their arm stack; everything else routes
  // to the inferred zone (or the drop-target zone as fallback).
  const makeOnDrop = (zoneId) => (e) => {
    e.preventDefault();
    try {
      const item     = JSON.parse(e.dataTransfer.getData("item"));
      const inferred = inferZone(item);

      // Bracelet items → one per wrist slot
      if (inferred === "bracelet_left" || inferred === "bracelet_right") {
        const targetSide = zoneId === "bracelet_right" ? "right" : "left";
        let fromSide = null;
        try { fromSide = e.dataTransfer.getData("fromBraceletSide") || null; } catch {}
        setBraceletStacks((prev) => {
          if (fromSide) {
            // Moving from one wrist to the other
            return { ...prev, [fromSide]: null, [targetSide]: item };
          }
          // New bracelet from rail — skip if already placed
          if (prev.left?.id === item.id || prev.right?.id === item.id) return prev;
          // Fill target slot; fall back to other wrist if taken
          if (!prev[targetSide]) return { ...prev, [targetSide]: item };
          const otherSide = targetSide === "left" ? "right" : "left";
          if (!prev[otherSide]) return { ...prev, [otherSide]: item };
          return { ...prev, [targetSide]: item }; // both full → replace target
        });
      } else {
        const target = inferred || zoneId;
        setOutfit((prev) => {
          const next = { ...prev, [target]: item };
          if (target === "left_shoe") next.right_shoe = prev.right_shoe || item;
          if (target === "left_sock") next.right_sock = prev.right_sock || item;
          return next;
        });
      }
    } catch {}
    setIsDragging(false);
    setDragZone(null);
  };

  const smartFill = () => {
    const next = { ...outfit };
    const nextStacks = { left: braceletStacks.left, right: braceletStacks.right };
    for (const item of items.filter((it) => it.is_mine)) {
      const zone = inferZone(item);
      if (!zone) continue;
      if (zone === "bracelet_left" || zone === "bracelet_right") {
        if (!nextStacks.left) nextStacks.left = item;
        else if (!nextStacks.right) nextStacks.right = item;
      } else if (zone === "left_shoe" && !next.left_shoe) {
        next.left_shoe  = item;
        next.right_shoe = next.right_shoe || item;
      } else if (zone === "left_sock" && !next.left_sock) {
        next.left_sock  = item;
        next.right_sock = next.right_sock || item;
      } else if (!next[zone]) {
        next[zone] = item;
      }
    }
    setOutfit(next);
    setBraceletStacks(nextStacks);
  };

  // ── Recommendation accept / skip ──────────────────────────────────────────
  const onAcceptRec = useCallback((slotId, rec) => {
    if (rec.source === "closet") {
      const fullItem = items.find((i) => i.id === rec.id);
      setOutfit((prev) => ({ ...prev, [slotId]: fullItem ?? {
        id: rec.id, title: rec.title, brand: rec.brand,
        icon_url: rec.icon_url, image_url: rec.image_url,
        color: rec.color, is_mine: true,
      }}));
    } else {
      setOutfit((prev) => ({ ...prev, [slotId]: {
        id: null, title: rec.title, brand: rec.brand,
        icon_url: rec.extractedUrl || null,
        image_url: rec.image_url, color: rec.color, price: rec.price, is_mine: false,
      }}));
    }
    axios.post(`${API_BASE}/recommend/feedback`,
      { item_id: rec.id, slot: slotId, signal: "accept" },
      { headers: { ...auth(), "Content-Type": "application/json" } }
    ).catch(console.error);
    axios.post(`${API_BASE}/recommend/events`,
      { event_type: "recommendation_added", item_id: rec.id, context: { slot: slotId, score: rec.score, source: rec.source } },
      { headers: { ...auth(), "Content-Type": "application/json" } }
    ).catch(console.error);
  }, [items]);

  const onSkipRec = useCallback((slotId) => {
    const currentIdx = recCardIndex[slotId] || 0;
    const slotRecs   = recs[slotId] || [];
    const currentRec = slotRecs[currentIdx];
    if (currentRec) {
      axios.post(`${API_BASE}/recommend/feedback`,
        { item_id: currentRec.id, slot: slotId, signal: "reject" },
        { headers: { ...auth(), "Content-Type": "application/json" } }
      ).catch(console.error);
      axios.post(`${API_BASE}/recommend/events`,
        { event_type: "recommendation_skipped", item_id: currentRec.id, context: { slot: slotId, score: currentRec.score, source: currentRec.source } },
        { headers: { ...auth(), "Content-Type": "application/json" } }
      ).catch(console.error);
    }
    setRecCardIndex((prev) => ({ ...prev, [slotId]: (currentIdx + 1) % (slotRecs.length || 1) }));
  }, [recCardIndex, recs]);

  const onConfirmPreview = useCallback((slotId) => {
    const rec = previews[slotId];
    if (!rec) return;
    onAcceptRec(slotId, rec);
    setPreviews((prev) => { const next = {...prev}; delete next[slotId]; return next; });
  }, [previews, onAcceptRec]);

  const onCancelPreview = useCallback((slotId) => {
    setPreviews((prev) => { const next = {...prev}; delete next[slotId]; return next; });
  }, []);

  const onSelectSlot = useCallback((zoneId) => {
    setActiveRecSlot((prev) => {
      if (prev !== zoneId) { setRecs({}); setPreviews({}); }
      return zoneId;
    });
  }, []);

  // Click-to-place: bracelets go to left stack; others go to their inferred zone.
  const clickPlace = useCallback((item) => {
    const zone = inferZone(item);
    if (!zone) return;
    if (zone === "bracelet_left" || zone === "bracelet_right") {
      setBraceletStacks((prev) => {
        if (prev.left?.id === item.id || prev.right?.id === item.id) return prev;
        if (!prev.left) return { ...prev, left: item };
        if (!prev.right) return { ...prev, right: item };
        return prev; // both slots occupied
      });
      return;
    }
    setOutfit((prev) => {
      const next = { ...prev, [zone]: item };
      if (zone === "left_shoe")  next.right_shoe = prev.right_shoe || item;
      if (zone === "left_sock")  next.right_sock = prev.right_sock || item;
      return next;
    });
  }, []);

  // ── Save flow ─────────────────────────────────────────────────────────────
  const openSave = () => {
    if (!filledCount) return;
    const d = new Date();
    setSaveName(`Look — ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`);
    setIsPrivate(false);
    setSaveModal(true);
  };

  const confirmSave = async () => {
    setSaving(true);
    const outfitItems = [];

    for (const [slot, item] of Object.entries(outfit)) {
      if (!item) continue;
      const nudge = nudgeOffsetMapRef.current[slot] || { x: 0, y: 0 };
      outfitItems.push({
        slot,
        closet_item_id: item.id || null,
        catalog_data: !item.id ? {
          title:     item.title     || null,
          brand:     item.brand     || null,
          image_url: item.image_url || null,
          icon_url:  item.icon_url  || null,
          color:     item.color     || null,
          price:     item.price     || null,
        } : null,
        nudge_x: Math.round(nudge.x),
        nudge_y: Math.round(nudge.y),
      });
    }
    for (const [side, slotKey] of [["left", "bracelet_left"], ["right", "bracelet_right"]]) {
      const item = braceletStacks[side];
      if (!item) continue;
      const nudge = nudgeOffsetMapRef.current[slotKey] || { x: 0, y: 0 };
      outfitItems.push({
        slot:           slotKey,
        closet_item_id: item.id || null,
        catalog_data: !item.id ? {
          title:     item.title     || null,
          brand:     item.brand     || null,
          image_url: item.image_url || null,
          icon_url:  item.icon_url  || null,
        } : null,
        nudge_x: Math.round(nudge.x),
        nudge_y: Math.round(nudge.y),
      });
    }

    try {
      await axios.post(
        `${API_BASE}/outfits`,
        { name: saveName.trim() || "My Look", is_private: isPrivate, items: outfitItems },
        { headers: { ...auth(), "Content-Type": "application/json" } }
      );
      setSaveModal(false);
      fetchSaved();
    } catch (err) {
      alert(err?.response?.data?.message || "Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  const deleteOutfit = async (id) => {
    if (!window.confirm("Delete this look?")) return;
    try {
      await axios.delete(`${API_BASE}/outfits/${id}`, { headers: auth() });
      fetchSaved();
    } catch {}
  };

  const loadOutfit = (saved) => {
    const next = Object.fromEntries(ZONES.map((z) => [z.id, null]));
    let leftBracelet  = null;
    let rightBracelet = null;
    const restoredNudges = {};

    for (const it of saved.items) {
      let item;
      if (it.closet_item_id) {
        item = {
          id:            it.closet_item_id,
          filename:      it.filename,
          brand:         it.brand,
          icon_url:      iconUrl(it.icon_path),
          image_url:     it.owner_user_id
            ? `${API_BASE}/static/${it.owner_user_id}/${it.filename}`
            : null,
          is_mine:       true,
          owner_initial: null,
        };
      } else if (it.catalog_data) {
        item = {
          id:        null,
          title:     it.catalog_data.title,
          brand:     it.catalog_data.brand,
          icon_url:  it.catalog_data.icon_url,
          image_url: it.catalog_data.image_url,
          color:     it.catalog_data.color,
          price:     it.catalog_data.price,
          is_mine:   false,
        };
      } else {
        continue;
      }

      if (it.nudge_x || it.nudge_y) {
        restoredNudges[it.slot] = { x: it.nudge_x || 0, y: it.nudge_y || 0 };
      }

      if (it.slot === "bracelet_left" || it.slot.startsWith("bracelet_left_")) {
        if (!leftBracelet) leftBracelet = item;
      } else if (it.slot === "bracelet_right" || it.slot.startsWith("bracelet_right_")) {
        if (!rightBracelet) rightBracelet = item;
      } else if (it.slot === "bracelet") {
        // legacy: single bracelet slot → left arm
        if (!leftBracelet) leftBracelet = item;
      } else if (it.slot in next) {
        next[it.slot] = item;
      }
    }

    setOutfit(next);
    setBraceletStacks({ left: leftBracelet, right: rightBracelet });
    nudgeOffsetMapRef.current = { ...restoredNudges };
    setLoadedNudges(restoredNudges);
    setNudgeKey((k) => k + 1);
  };

  // ── Hover preview ─────────────────────────────────────────────────────────
  const onEnter = (e, item) => {
    if (!item || isDragging) return;
    const r = e.currentTarget.getBoundingClientRect();
    setHovered({ url: item.image_url, x: r.right + 12, y: r.top });
  };
  const onLeave = () => setHovered(null);

  // ── Item grouping ─────────────────────────────────────────────────────────
  const myItems = items.filter((it) => it.is_mine);
  const byOwner = {};
  for (const it of items.filter((it) => !it.is_mine)) {
    const key = it.owner_email || "Unknown";
    (byOwner[key] = byOwner[key] || []).push(it);
  }

  const RAIL_GROUPS = [
    { label: "Tops",        zones: new Set(["inner_top"]) },
    { label: "Bottoms",     zones: new Set(["inner_bottom", "outer_bottom"]) },
    { label: "Outerwear",   zones: new Set(["outer_top"]) },
    { label: "Shoes",       zones: new Set(["left_shoe", "right_shoe"]) },
    { label: "Accessories", zones: new Set(["hat", "necklace", "bracelet_left", "bracelet_right", "bag"]) },
    { label: "Innerwear",   zones: new Set(["innerwear", "underwear", "left_sock", "right_sock"]) },
  ];
  const myItemsByCategory = (() => {
    const buckets = Object.fromEntries(RAIL_GROUPS.map((g) => [g.label, []]));
    buckets["Other"] = [];
    for (const item of myItems) {
      const zone = inferZone(item);
      const group = RAIL_GROUPS.find((g) => g.zones.has(zone));
      (buckets[group ? group.label : "Other"]).push(item);
    }
    return [...RAIL_GROUPS.map((g) => g.label), "Other"]
      .map((label) => ({ label, items: buckets[label] }))
      .filter((g) => g.items.length > 0);
  })();

  const outfitIds   = new Set(Object.values(outfit).filter(Boolean).map((i) => i.id));
  const braceletIds = new Set([braceletStacks.left?.id, braceletStacks.right?.id].filter(Boolean));
  const usedIds = new Set([...outfitIds, ...braceletIds]);

  const hasAnyFilled = usedIds.size > 0;
  const openZone = (id) => !outfit[id];
  const isCompatible = (item) => {
    if (!hasAnyFilled || usedIds.has(item.id)) return false;
    const zone = inferZone(item);
    if (!zone) return false;
    // Bracelets: compatible when at least one wrist slot is free
    if (zone === "bracelet_left" || zone === "bracelet_right")
      return !braceletStacks.left || !braceletStacks.right;
    if (zone === "left_shoe" || zone === "right_shoe") {
      return openZone("left_shoe") || openZone("right_shoe");
    }
    if (zone === "left_sock" || zone === "right_sock") {
      return openZone("left_sock") || openZone("right_sock");
    }
    return openZone(zone);
  };

  return (
    <Layout>
      <div className="pb-page" ref={pageRef}>

        {/* ── Header ── */}
        <header className="pb-header">
          <div className="pb-header-left">
            <span className="pb-wordmark">My Closet</span>
            <span className="pb-breadcrumb">/ Studio</span>
          </div>

          {(circles.length > 0 || activeCircle) && (
            <div className="pb-circle-row">
              {activeCircle ? (
                <>
                  <span className="pb-circle-pill active">{activeCircle.name}</span>
                  <button className="pb-circle-pill clear-btn" onClick={() => setActiveCircle(null)}>
                    ✕ Just Me
                  </button>
                </>
              ) : (
                circles.map((c) => (
                  <button key={c.id} className="pb-circle-pill" onClick={() => setActiveCircle(c)}>
                    {c.name}
                  </button>
                ))
              )}
            </div>
          )}

          <div className="pb-header-right">
            {filledCount > 0 && (
              <span className="pb-item-count">{filledCount} piece{filledCount !== 1 ? "s" : ""}</span>
            )}
            <button className="pb-btn-smart" onClick={smartFill} title="Auto-fill zones from closet">
              ✦ Smart Fill
            </button>
            <button className="pb-btn-save" onClick={openSave} disabled={!filledCount}>
              Preserve
            </button>
            <button className="pb-btn-reset" onClick={resetOutfit}>Clear</button>
          </div>
        </header>

        {/* ── Stage: canvas + editorial ── */}
        <div className="pb-stage">

          {/* Slot picker sidebar (left) */}
          {recommenderOn && Object.values(outfit).some(Boolean) && (
            <div className="pb-slot-sidebar">
              <div className="pb-slot-sidebar-label">Suggest for…</div>
              <div className="pb-slot-list">
                {SLOT_PICKER.filter((s) => !outfit[REC_SLOT_TO_ZONE[s.id] || s.id]).map((s) => (
                  <button
                    key={s.id}
                    className={`pb-slot-btn${activeRecSlot === s.id ? " pb-slot-btn--active" : ""}`}
                    onClick={() => onSelectSlot(s.id)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Canvas area */}
          <div className="pb-canvas-area">
            <PortraitCanvas
              outfit={outfit}
              isDragging={isDragging}
              dragZone={dragZone}
              altHeld={altHeld}
              makeOnDrop={makeOnDrop}
              removeSlot={removeSlot}
              onEnter={onEnter}
              onLeave={onLeave}
              flipped={flipped}
              recs={recsLoading ? {} : recs}
              recCardIndex={recCardIndex}
              onAcceptRec={onAcceptRec}
              onSkipRec={onSkipRec}
              previews={previews}
              onConfirmPreview={onConfirmPreview}
              onCancelPreview={onCancelPreview}
              onGhostDragStart={(zoneId) => { setIsDragging(true); setDragZone(zoneId); }}
              onGhostDragEnd={() => { setIsDragging(false); setDragZone(null); }}
              recommenderOn={recommenderOn}
              activeRecSlot={activeRecSlot}
              onSelectSlot={onSelectSlot}
              braceletStacks={braceletStacks}
              removeBracelet={removeBracelet}
              nudgeKey={nudgeKey}
              loadedNudges={loadedNudges}
              onNudgeChange={(zoneId, off) => { nudgeOffsetMapRef.current[zoneId] = off; }}
            />
            <button
              className={`pb-flip-btn${flipped ? " pb-flip-btn--back" : ""}`}
              onClick={() => setFlipped(f => !f)}
              title={flipped ? "View outer outfit" : "View underlayers"}
            >
              {flipped ? "↩ Outer" : "↻ Underlayers"}
            </button>

            {/* Recommender toggles */}
            <div className="pb-rec-controls">
              <label className="pb-toggle-label">
                <input type="checkbox" checked={recommenderOn} onChange={(e) => setRecommenderOn(e.target.checked)} />
                <span className={`pb-toggle-track${recommenderOn ? " pb-toggle-track--on" : ""}`}>
                  <span className="pb-toggle-thumb" />
                </span>
                <span className="pb-toggle-text">✦ Recommend</span>
              </label>
              {recommenderOn && (
                <label className="pb-toggle-label">
                  <input type="checkbox" checked={catalogMode} onChange={(e) => setCatalogMode(e.target.checked)} />
                  <span className={`pb-toggle-track${catalogMode ? " pb-toggle-track--on" : ""}`}>
                    <span className="pb-toggle-thumb" />
                  </span>
                  <span className="pb-toggle-text">🛒 Catalog</span>
                </label>
              )}
              {recommenderOn && (
                <button
                  className="pb-gender-toggle"
                  onClick={() => setRecGender((g) => g === "male" ? "female" : "male")}
                  title="Toggle gender filter for recommendations"
                >
                  {recGender === "male" ? "♂ M" : "♀ F"}
                </button>
              )}
              {recsLoading && (
                <div className="pb-rec-loading">
                  <span className="pb-rec-dot" /><span className="pb-rec-dot" /><span className="pb-rec-dot" />
                </div>
              )}
            </div>
          </div>

          {/* Editorial column */}
          <aside className="pb-editorial">
            <EditorialColumn
              outfit={outfit}
              savedOutfits={savedOutfits}
              onLoad={loadOutfit}
              onDelete={deleteOutfit}
              activeCircle={activeCircle}
            />
          </aside>
        </div>

        {/* ── Recommendations band ── */}
        {recommenderOn && hasRecs && (
          <div className="pb-rec-band">
            <span className="pb-rec-band-label">✦ For You</span>
            <div className="pb-rec-band-track">
              {Object.entries(recs).flatMap(([slot, candidates]) => {

                const previewed = previews[slot];
                const previewMissing = previewed && !candidates.some(
                  (c) => c.source === previewed.source && c.id === previewed.id
                );
                const allRecs = previewMissing ? [previewed, ...candidates] : candidates;

                return allRecs.map((rec, i) => (
                  <RecRailItem
                    key={`${slot}-${rec.id ?? rec.image_url ?? i}`}
                    rec={rec}
                    slot={slot}
                    devMode={devMode}
                    isActive={!!(previewed && rec.source === previewed.source &&
                      (rec.id != null ? rec.id === previewed.id : rec.image_url === previewed.image_url))}
                    onClickPlace={() => setPreviews((prev) => ({ ...prev, [slot]: rec }))}
                    onExtracted={(url) => {
                      if (rec.source !== "catalog") return;
                      const srcUrl = rec.image_url;
                      // Update every catalog item in this slot sharing the same image_url
                      // (dedup means only one fires the request; all should get the result)
                      setRecs((prev) => ({
                        ...prev,
                        [slot]: prev[slot].map((r) =>
                          r.source === "catalog" && r.image_url === srcUrl
                            ? { ...r, extractedUrl: url }
                            : r
                        ),
                      }));
                      setPreviews((prev) => {
                        const p = prev[slot];
                        if (!p || p.source !== "catalog" || p.image_url !== srcUrl) return prev;
                        return { ...prev, [slot]: { ...p, extractedUrl: url } };
                      });
                    }}
                    onDragStart={(e) => {
                      e.dataTransfer.setData("item", JSON.stringify({
                        id:        rec.id,
                        title:     rec.title,
                        brand:     rec.brand,
                        color:     rec.color,
                        category:  rec.category || SLOT_TO_CATEGORY[slot],
                        icon_url:  rec.extractedUrl || rec.icon_url,
                        image_url: rec.image_url,
                        is_mine:   rec.source === "closet",
                      }));
                      setIsDragging(true);
                      setDragZone(slot);
                    }}
                    onDragEnd={() => { setIsDragging(false); setDragZone(null); }}
                  />
                ));
              })}
            </div>
            <button
              className={`pb-dev-toggle${devMode ? " pb-dev-toggle--on" : ""}`}
              onClick={() => setDevMode(d => !d)}
              title="Developer mode — show reset controls"
            >DEV</button>
          </div>
        )}

        {/* ── Bottom closet rail ── */}
        <div className="pb-rail">
          <div className="pb-rail-track">
            {myItemsByCategory.map(({ label, items: groupItems }) => (
              <div key={label} className="pb-rail-section">
                <div className="pb-rail-section-label">{label}</div>
                <div className="pb-rail-section-items">
                  {groupItems.map((item) => (
                    <RailItem
                      key={item.id}
                      item={item}
                      used={usedIds.has(item.id)}
                      compatible={isCompatible(item)}
                      onClickPlace={() => clickPlace(item)}
                      onDragStart={(e) => {
                        e.dataTransfer.setData("item", JSON.stringify(item));
                        setIsDragging(true);
                        setDragZone(inferZone(item));
                      }}
                      onDragEnd={() => { setIsDragging(false); setDragZone(null); }}
                      onEnter={onEnter}
                      onLeave={onLeave}
                    />
                  ))}
                </div>
              </div>
            ))}

            {Object.entries(byOwner).map(([email, ownerItems]) => (
              <div key={email} className="pb-rail-section">
                <div className="pb-rail-section-label">{email.split("@")[0]}</div>
                <div className="pb-rail-section-items">
                  {ownerItems.map((item) => (
                    <RailItem
                      key={item.id}
                      item={item}
                      used={usedIds.has(item.id)}
                      compatible={isCompatible(item)}
                      onClickPlace={() => clickPlace(item)}
                      onDragStart={(e) => {
                        e.dataTransfer.setData("item", JSON.stringify(item));
                        setIsDragging(true);
                        setDragZone(inferZone(item));
                      }}
                      onDragEnd={() => { setIsDragging(false); setDragZone(null); }}
                      onEnter={onEnter}
                      onLeave={onLeave}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Save modal ── */}
      {saveModal && (
        <div className="pb-modal-backdrop" onClick={() => setSaveModal(false)}>
          <div className="pb-save-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="pb-modal-title">Preserve this look</h3>
            <input
              className="pb-save-input"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="Give it a name"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && confirmSave()}
            />
            <label className="pb-privacy-row">
              <input
                type="checkbox"
                checked={!isPrivate}
                onChange={(e) => setIsPrivate(!e.target.checked)}
              />
              <span className="pb-privacy-label">
                {isPrivate ? "Private — only you can see this" : "Shared with your circle"}
              </span>
              <span className={`pb-privacy-pill ${isPrivate ? "pb-pill-private" : "pb-pill-shared"}`}>
                {isPrivate ? "Private" : "Circle"}
              </span>
            </label>
            <div className="pb-modal-actions">
              <button className="pb-btn-cancel" onClick={() => setSaveModal(false)}>Cancel</button>
              <button className="pb-btn-confirm" onClick={confirmSave} disabled={saving}>
                {saving ? "Saving…" : "Save Look"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Hover preview ── */}
      {hovered?.url && !isDragging && (
        <div
          className="pb-hover-card"
          style={{
            top:       hovered.y,
            left:      hovered.x,
            transform: hovered.above ? "translate(-50%, -100%)" : "none",
          }}
        >
          <img src={hovered.url} alt={hovered.title || "preview"} />
          {hovered.reason && (
            <p className="pb-hover-reason">{hovered.reason}</p>
          )}
          {hovered.shopUrl && (
            <a
              href={hovered.shopUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="pb-hover-shop-link"
              onClick={(e) => e.stopPropagation()}
            >
              View on site →
            </a>
          )}
        </div>
      )}
    </Layout>
  );
}

// ── computeZoneTops ───────────────────────────────────────────────────────────
function computeZoneTops(outfit, previews) {
  const has = (id) => !!(outfit[id] || previews?.[id]);

  const STACK = [
    { ids: ["hat"],                                       h:  60 },
    { ids: ["necklace"],                                  h:  38 },
    { ids: ["outer_top"],                                 h: 130 },
    { ids: ["inner_top",    "innerwear"],                 h: 120 },
    { ids: ["inner_bottom", "outer_bottom", "underwear"], h: 130 },
    { ids: ["left_shoe",    "right_shoe"],                h:  62 },
  ];

  const tops = {};
  let y = 0;
  for (const group of STACK) {
    const groupY = y;
    for (const id of group.ids) tops[id] = groupY;
    if (group.ids.some(has)) y += group.h;
  }

  tops["bag"]           = tops["inner_bottom"] + 2;
  tops["left_sock"]     = tops["left_shoe"]    + 8;
  tops["right_sock"]    = tops["right_shoe"]   + 8;
  // Bracelet wrists: ~65% down from inner_top top edge (sleeve level)
  tops["bracelet_left"]  = tops["inner_top"] + 78;
  tops["bracelet_right"] = tops["inner_top"] + 78;

  return tops;
}

// ── PortraitCanvas ────────────────────────────────────────────────────────────
function PortraitCanvas({
  outfit, isDragging, dragZone, altHeld, makeOnDrop, removeSlot,
  onEnter, onLeave, flipped, recs, recCardIndex, onAcceptRec, onSkipRec,
  previews, onConfirmPreview, onCancelPreview, onGhostDragStart, onGhostDragEnd,
  recommenderOn, activeRecSlot, onSelectSlot,
  braceletStacks, removeBracelet,
  nudgeKey, loadedNudges, onNudgeChange,
}) {
  const isEmpty    = !Object.values(outfit).some(Boolean)
    && !braceletStacks.left && !braceletStacks.right;
  const frontZones = ZONES.filter((z) => z.face === "front");
  const backZones  = ZONES.filter((z) => z.face === "back");
  const hasBackItems = backZones.some((z) => outfit[z.id]);

  const zoneTops = computeZoneTops(outfit, previews);

  // Canvas height: min 260px; expands to fit tallest placed item.
  const canvasHeight = isEmpty && !Object.keys(previews || {}).length
    ? 260
    : ZONES
        .filter((z) => outfit[z.id] || previews?.[z.id])
        .reduce((m, z) => Math.max(m, (zoneTops[z.id] ?? z.top) + z.height + 28), 260);

  const zoneProps = (zone) => ({
    zone,
    computedTop:      zoneTops[zone.id] ?? zone.top,
    chosen:           outfit[zone.id],
    isDragging,
    dragZone,
    altHeld,
    onDrop:           makeOnDrop(zone.id),
    onRemove:         () => removeSlot(zone.id),
    onEnter,
    onLeave,
    recCandidates:    recs ? (recs[zone.id] || []) : [],
    recIdx:           recCardIndex ? (recCardIndex[zone.id] || 0) : 0,
    onAcceptRec,
    onSkipRec,
    preview:          previews ? (previews[zone.id] || null) : null,
    onConfirmPreview: () => onConfirmPreview(zone.id),
    onCancelPreview:  () => onCancelPreview(zone.id),
    onGhostDragStart,
    onGhostDragEnd,
    isActiveRec:      activeRecSlot === zone.id || REC_SLOT_TO_ZONE[activeRecSlot] === zone.id,
    initialNudge:     loadedNudges?.[zone.id],
    onNudgeChange:    (off) => onNudgeChange(zone.id, off),
  });

  // Whether a bracelet drag is in progress (both sides should highlight)
  const isBraceletDrag = isDragging &&
    (dragZone === "bracelet_left" || dragZone === "bracelet_right");

  return (
    <div className="pb-canvas-scene" style={{ height: canvasHeight }}>
      <div
        className={`pb-canvas-inner${flipped ? " pb-canvas-inner--flipped" : ""}${altHeld ? " pb-canvas--exploded" : ""}`}
        style={{ height: canvasHeight }}
      >
        {/* ── Front face ── */}
        <div className={`pb-canvas pb-canvas--front${isDragging ? " pb-canvas--dragging" : ""}`}>
          {isEmpty && !isDragging && (
            <div className="pb-canvas-empty">
              <span className="pb-empty-hint">Click or drag from your closet below</span>
              <span className="pb-empty-sub">Hold Alt to separate layers</span>
            </div>
          )}
          {frontZones.map((zone) => (
            <CanvasZone key={`${zone.id}-${nudgeKey}`} {...zoneProps(zone)} />
          ))}

          {/* Bracelet stacks — left and right arms */}
          {(["left", "right"]).map((side) => (
            <BraceletStack
              key={`${side}-${nudgeKey}`}
              side={side}
              item={braceletStacks[side]}
              computedTop={zoneTops["bracelet_left"]}
              removeBracelet={removeBracelet}
              isDragging={isBraceletDrag}
              onDrop={makeOnDrop(`bracelet_${side}`)}
              initialNudge={loadedNudges?.[`bracelet_${side}`]}
              onNudgeChange={(off) => onNudgeChange(`bracelet_${side}`, off)}
            />
          ))}
        </div>

        {/* ── Back face ── */}
        <div className="pb-canvas pb-canvas--back">
          <div className="pb-back-label">Underlayers</div>
          {!hasBackItems && (
            <div className="pb-canvas-empty" style={{ paddingTop: 80 }}>
              <span className="pb-empty-hint">No underlayers placed</span>
              <span className="pb-empty-sub">Add bra, undershirt, or underwear</span>
            </div>
          )}
          {backZones.map((zone) => (
            <CanvasZone key={`${zone.id}-${nudgeKey}`} {...zoneProps(zone)} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── BraceletSlot ─────────────────────────────────────────────────────────────
// One wrist slot holding a single bracelet. Draggable between wrists; nudgeable.
// Shows no visible border or background when empty — only highlights on drag-over.
function BraceletStack({ side, item, computedTop, removeBracelet, isDragging, onDrop, initialNudge, onNudgeChange }) {
  const [dragOver,    setDragOver]   = useState(false);
  const [nudgeOffset, setNudgeOffset] = useState(initialNudge || { x: 0, y: 0 });
  const [grabbing,    setGrabbing]   = useState(false);
  const nudgeDragging   = useRef(false);
  const nudgeStart      = useRef(null);
  const hasMoved        = useRef(false);
  const onNudgeChangeRef = useRef(onNudgeChange);
  const firstMount      = useRef(true);
  useEffect(() => { onNudgeChangeRef.current = onNudgeChange; }, [onNudgeChange]);

  const def = BRACELET_ZONE_DEF[side];

  // Reset nudge when the bracelet itself changes (skip on first mount to preserve initialNudge)
  const itemKey = item?.id ?? item?.image_url ?? null;
  useEffect(() => {
    if (firstMount.current) { firstMount.current = false; return; }
    const zero = { x: 0, y: 0 };
    setNudgeOffset(zero);
    onNudgeChangeRef.current?.(zero);
  }, [itemKey]);

  useEffect(() => {
    const onMove = (e) => {
      if (!nudgeDragging.current || !nudgeStart.current) return;
      const dx = e.clientX - nudgeStart.current.mouseX;
      const dy = e.clientY - nudgeStart.current.mouseY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasMoved.current = true;
      if (!hasMoved.current) return;
      const newOff = {
        x: Math.max(-150, Math.min(150, nudgeStart.current.offsetX + dx)),
        y: Math.max(-150, Math.min(150, nudgeStart.current.offsetY + dy)),
      };
      setNudgeOffset(newOff);
      onNudgeChangeRef.current?.(newOff);
    };
    const onUp = () => {
      if (!nudgeDragging.current) return;
      nudgeDragging.current = false;
      nudgeStart.current    = null;
      setGrabbing(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup",   onUp);
    };
  }, []);

  const handleMouseDown = (e) => {
    if (e.button !== 0 || !item) return;
    e.preventDefault();
    nudgeDragging.current = true;
    hasMoved.current      = false;
    nudgeStart.current    = { mouseX: e.clientX, mouseY: e.clientY, offsetX: nudgeOffset.x, offsetY: nudgeOffset.y };
    setGrabbing(true);
  };

  const url = item ? (item.icon_url || item.image_url) : null;

  return (
    <div
      className={[
        "pb-bracelet-stack",
        `pb-bracelet-stack--${side}`,
        isDragging ? "pb-bracelet-stack--target" : "",
        dragOver   ? "pb-bracelet-stack--dragover" : "",
      ].filter(Boolean).join(" ")}
      style={{
        position:  "absolute",
        top:       computedTop,
        left:      def.left,
        width:     def.width,
        height:    def.width, // square slot
        zIndex:    def.z,
        cursor:    item ? (grabbing ? "grabbing" : "grab") : "default",
        userSelect:"none",
        transform: (nudgeOffset.x || nudgeOffset.y) ? `translate(${nudgeOffset.x}px,${nudgeOffset.y}px)` : undefined,
      }}
      onMouseDown={handleMouseDown}
      onDragStart={(e) => e.preventDefault()}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { setDragOver(false); onDrop(e); }}
    >
      {!item && isDragging && (
        <span className="pb-bracelet-empty-label">
          {side === "left" ? "L" : "R"} Wrist
        </span>
      )}
      {item && url && (
        <div
          className="pb-bracelet-item"
          draggable
          onDragStart={(e) => {
            e.stopPropagation();
            e.dataTransfer.setData("item", JSON.stringify(item));
            e.dataTransfer.setData("fromBraceletSide", side);
          }}
          title="Drag to other wrist · Click × to remove"
        >
          <img src={url} alt="" className="pb-bracelet-img" draggable={false} />
          <button
            className="pb-bracelet-remove"
            onClick={(e) => { e.stopPropagation(); removeBracelet(side); }}
            title="Remove"
          >×</button>
        </div>
      )}
    </div>
  );
}

// ── CanvasZone ────────────────────────────────────────────────────────────────
function CanvasZone({ zone, computedTop, chosen, isDragging, dragZone, altHeld, onDrop, onRemove, onEnter, onLeave, recCandidates, recIdx, onAcceptRec, onSkipRec, preview, onConfirmPreview, onCancelPreview, onGhostDragStart, onGhostDragEnd, isActiveRec, initialNudge, onNudgeChange }) {
  const [dragOver,    setDragOver]   = useState(false);
  const [nudgeOffset, setNudgeOffset] = useState(initialNudge || { x: 0, y: 0 });
  const [grabbing,    setGrabbing]   = useState(false);
  const nudgeDragging    = useRef(false);
  const nudgeStart       = useRef(null);
  const hasMoved         = useRef(false);
  const onNudgeChangeRef  = useRef(onNudgeChange);
  const zoneRef          = useRef(null);
  const resizeDragging   = useRef(false);
  const resizeStart      = useRef(null);
  const justResized      = useRef(false);
  const [scale, setScale]       = useState(1.0);
  const [resizing, setResizing] = useState(false);
  const firstMount       = useRef(true);
  useEffect(() => { onNudgeChangeRef.current = onNudgeChange; }, [onNudgeChange]);

  // Reset nudge and scale when the placed item changes (skip first mount to preserve initialNudge)
  const itemKey = chosen?.id ?? chosen?.image_url ?? preview?.image_url ?? null;
  useEffect(() => {
    if (firstMount.current) { firstMount.current = false; return; }
    const zero = { x: 0, y: 0 };
    setNudgeOffset(zero);
    setScale(1.0);
    onNudgeChangeRef.current?.(zero);
  }, [itemKey]);

  // Global mouse tracking for nudge repositioning and corner resize.
  useEffect(() => {
    const onMove = (e) => {
      if (resizeDragging.current && resizeStart.current) {
        const { centerX, centerY, startDist, startScale } = resizeStart.current;
        if (startDist < 4) return;
        const dx = e.clientX - centerX;
        const dy = e.clientY - centerY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        setScale(Math.max(0.25, Math.min(3.0, startScale * dist / startDist)));
        return;
      }
      if (!nudgeDragging.current || !nudgeStart.current) return;
      const dx = e.clientX - nudgeStart.current.mouseX;
      const dy = e.clientY - nudgeStart.current.mouseY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasMoved.current = true;
      if (!hasMoved.current) return;
      const newOff = {
        x: Math.max(-150, Math.min(150, nudgeStart.current.offsetX + dx)),
        y: Math.max(-150, Math.min(150, nudgeStart.current.offsetY + dy)),
      };
      setNudgeOffset(newOff);
      onNudgeChangeRef.current?.(newOff);
    };
    const onUp = () => {
      if (resizeDragging.current) {
        resizeDragging.current = false;
        resizeStart.current    = null;
        setResizing(false);
        document.body.style.cursor = "";
        justResized.current = true;
        setTimeout(() => { justResized.current = false; }, 150);
        return;
      }
      if (!nudgeDragging.current) return;
      nudgeDragging.current = false;
      nudgeStart.current    = null;
      setGrabbing(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup",   onUp);
    };
  }, []);

  const handleNudgeDown = (e) => {
    if (e.button !== 0) return;
    if (!chosen && !preview) return;
    e.preventDefault();
    nudgeDragging.current = true;
    hasMoved.current      = false;
    nudgeStart.current    = { mouseX: e.clientX, mouseY: e.clientY, offsetX: nudgeOffset.x, offsetY: nudgeOffset.y };
    setGrabbing(true);
  };

  const startResize = useCallback((e) => {
    if (e.button !== 0 || (!chosen && !preview)) return;
    e.preventDefault();
    e.stopPropagation();
    const rect = zoneRef.current?.getBoundingClientRect();
    if (!rect) return;
    const centerX = rect.left + rect.width  / 2;
    const centerY = rect.top  + rect.height / 2;
    const dx = e.clientX - centerX;
    const dy = e.clientY - centerY;
    const cursor = window.getComputedStyle(e.currentTarget).cursor;
    resizeStart.current = { centerX, centerY, startDist: Math.sqrt(dx*dx + dy*dy), startScale: scale, cursor };
    resizeDragging.current = true;
    setResizing(true);
    document.body.style.cursor = cursor;
  }, [chosen, preview, scale]);

  const rec           = (!chosen && !preview && recCandidates?.length > 0) ? (recCandidates[recIdx] || recCandidates[0]) : null;
  const displayUrl    = chosen ? (chosen.icon_url || chosen.image_url) : null;
  const recDisplayUrl = rec   ? (rec.extractedUrl || rec.icon_url || rec.image_url) : null;
  const previewUrl    = preview ? (preview.extractedUrl || preview.icon_url || preview.image_url) : null;
  const isPlaceholder = chosen && !chosen.icon_url;
  const brightness    = altHeld ? 1 : (zone.recede ?? 1);
  const isTarget      = isDragging && (dragZone ? dragZone === zone.id : !chosen);
  const isNudgeable   = !!(chosen || (preview && previewUrl));

  return (
    <div
      ref={zoneRef}
      className={[
        "pb-zone",
        (chosen || (preview && previewUrl)) ? "pb-zone--filled" :
        rec                 ? "pb-zone--ghost"   : "pb-zone--empty",
        isActiveRec  ? "pb-zone--activerec"  : "",
        dragOver ? "pb-zone--dragover" : "",
        isTarget && !chosen ? "pb-zone--target" : "",
        altHeld && chosen   ? "pb-zone--exploded" : "",
      ].filter(Boolean).join(" ")}
      style={{
        top:        computedTop ?? zone.top,
        left:       zone.left,
        width:      zone.width,
        height:     zone.height,
        zIndex:     zone.z,
        userSelect: "none",
        cursor:     grabbing ? "grabbing" : resizing ? (resizeStart.current?.cursor || "nw-resize") : isNudgeable ? "grab" : "default",
        transform:  (nudgeOffset.x || nudgeOffset.y || scale !== 1)
          ? `translate(${nudgeOffset.x}px,${nudgeOffset.y}px) scale(${scale})`
          : undefined,
        transformOrigin: "center center",
      }}
      onMouseDown={handleNudgeDown}
      onDragStart={(e) => e.preventDefault()}
      onClick={() => { if (chosen && !hasMoved.current && !justResized.current) onRemove(); }}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { setDragOver(false); onDrop(e); }}
      onMouseEnter={(e) => chosen && onEnter(e, chosen)}
      onMouseLeave={onLeave}
    >
      {displayUrl ? (
        <>
          <img
            src={displayUrl}
            alt=""
            className="pb-zone-img"
            draggable={false}
            title="Click to remove · Drag to reposition"
            style={{
              opacity: isPlaceholder ? 0.55 : 1,
              filter: `brightness(${brightness}) drop-shadow(0 2px 8px rgba(0,0,0,0.9)) drop-shadow(0 8px 28px rgba(0,0,0,0.6)) drop-shadow(0 20px 50px rgba(0,0,0,0.25))`,
            }}
          />
          {!chosen.is_mine && chosen.owner_initial && (
            <span className="circle-owner-badge" style={{ position: "absolute", top: 4, right: 4, zIndex: 1 }}>
              {chosen.owner_initial}
            </span>
          )}
        </>
      ) : preview && previewUrl ? (
        <>
          <img
            src={previewUrl}
            alt={preview.title || ""}
            className="pb-zone-img"
            draggable={false}
            style={{
              opacity: 1,
              filter: `brightness(${brightness}) drop-shadow(0 2px 8px rgba(0,0,0,0.9)) drop-shadow(0 8px 28px rgba(0,0,0,0.6)) drop-shadow(0 20px 50px rgba(0,0,0,0.25))`,
            }}
          />
          <div className="pb-preview-overlay">
            <button
              className="pb-preview-btn pb-preview-btn--confirm"
              title="Add to outfit"
              onClick={(e) => { e.stopPropagation(); onConfirmPreview(); }}
            >✓</button>
            <button
              className="pb-preview-btn pb-preview-btn--cancel"
              title="Back to suggestions"
              onClick={(e) => { e.stopPropagation(); onCancelPreview(); }}
            >✕</button>
          </div>
        </>
      ) : rec && recDisplayUrl ? (
        <div
          className="pb-ghost-drag"
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData("item", JSON.stringify({
              id:        rec.id,
              title:     rec.title,
              brand:     rec.brand,
              color:     rec.color,
              category:  rec.category || SLOT_TO_CATEGORY[zone.id],
              icon_url:  rec.extractedUrl || rec.icon_url,
              image_url: rec.image_url,
              is_mine:   rec.source === "closet",
            }));
            onGhostDragStart && onGhostDragStart(zone.id);
          }}
          onDragEnd={() => onGhostDragEnd && onGhostDragEnd()}
        >
          <img
            src={recDisplayUrl}
            alt={rec.title || ""}
            className="pb-zone-img"
            draggable={false}
            style={{ opacity: 0.42, filter: "brightness(0.88) saturate(0.75)" }}
          />
        </div>
      ) : (
        isTarget && <span className="pb-zone-label">{zone.label}</span>
      )}
      {isNudgeable && (
        <>
          <div className="pb-zone-corner pb-zone-corner--tl" onMouseDown={startResize} onClick={(e) => e.stopPropagation()} />
          <div className="pb-zone-corner pb-zone-corner--tr" onMouseDown={startResize} onClick={(e) => e.stopPropagation()} />
          <div className="pb-zone-corner pb-zone-corner--bl" onMouseDown={startResize} onClick={(e) => e.stopPropagation()} />
          <div className="pb-zone-corner pb-zone-corner--br" onMouseDown={startResize} onClick={(e) => e.stopPropagation()} />
        </>
      )}
    </div>
  );
}

// ── EditorialColumn ───────────────────────────────────────────────────────────
function EditorialColumn({ outfit, savedOutfits, onLoad, onDelete, activeCircle }) {
  const editorial = computeEditorial(outfit);

  return (
    <div className="pb-edit">
      {!editorial ? (
        <div className="pb-edit-empty">
          <p className="pb-edit-tagline">Your look will speak here.</p>
        </div>
      ) : (
        <>
          <div className="pb-edit-name">{editorial.outfitName}</div>
          <div className="pb-edit-mood">{editorial.mood}</div>

          {editorial.occasions.length > 0 && (
            <div className="pb-edit-section">
              <div className="pb-edit-label">For</div>
              <div className="pb-edit-chips">
                {editorial.occasions.slice(0, 4).map((o) => (
                  <span key={o} className="pb-chip">{o}</span>
                ))}
              </div>
            </div>
          )}

          {editorial.formalityAvg !== null && (
            <div className="pb-edit-section">
              <div className="pb-edit-label">Formality</div>
              <div className="pb-formality-bar">
                <div
                  className="pb-formality-fill"
                  style={{ width: `${Math.min(100, editorial.formalityAvg * 10)}%` }}
                />
              </div>
              <div className="pb-formality-labels">
                <span>Casual</span><span>Formal</span>
              </div>
            </div>
          )}

          {editorial.seasons.length > 0 && (
            <div className="pb-edit-section">
              <div className="pb-edit-label">Season</div>
              <div className="pb-edit-chips">
                {editorial.seasons.slice(0, 3).map((s) => (
                  <span key={s} className="pb-chip pb-chip--season">{s}</span>
                ))}
              </div>
            </div>
          )}

          {editorial.vibes.length > 0 && (
            <div className="pb-edit-section">
              <div className="pb-edit-label">Vibe</div>
              <div className="pb-edit-chips">
                {editorial.vibes.slice(0, 5).map((v) => (
                  <span key={v} className="pb-chip pb-chip--vibe">{v}</span>
                ))}
              </div>
            </div>
          )}

          {editorial.styles.length > 0 && (
            <div className="pb-edit-section">
              <div className="pb-edit-label">Style</div>
              <div className="pb-edit-chips">
                {editorial.styles.slice(0, 4).map((s) => (
                  <span key={s} className="pb-chip">{s}</span>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {savedOutfits.length > 0 && (
        <div className="pb-saved-history">
          <div className="pb-edit-label">
            Saved Looks{activeCircle ? ` · ${activeCircle.name}` : ""}
          </div>
          <div className="pb-saved-scroll">
            {savedOutfits.map((s) => (
              <MiniSavedCard
                key={s.id}
                outfit={s}
                onLoad={() => onLoad(s)}
                onDelete={s.is_mine ? () => onDelete(s.id) : null}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── MiniSavedCard ─────────────────────────────────────────────────────────────
function MiniSavedCard({ outfit, onLoad, onDelete }) {
  const icons = outfit.items
    .filter((it) => it.icon_path)
    .slice(0, 2)
    .map((it) => iconUrl(it.icon_path));

  return (
    <div className="pb-mini-card">
      <div className="pb-mini-icons">
        {icons.length > 0 ? (
          icons.map((url, i) => <img key={i} src={url} alt="" className="pb-mini-icon" />)
        ) : (
          <span style={{ fontSize: "0.6rem", color: "#3a3a50" }}>—</span>
        )}
      </div>
      <div className="pb-mini-name" title={outfit.name}>{outfit.name}</div>
      <div className="pb-mini-actions">
        <button className="pb-mini-load" onClick={onLoad}>Load</button>
        {onDelete && <button className="pb-mini-del" onClick={onDelete}>✕</button>}
      </div>
    </div>
  );
}

// ── RecRailItem ───────────────────────────────────────────────────────────────
// Module-level set so duplicate requests are deduplicated across all instances
const _extracting = new Set();

const CASCADE_STEPS = 4; // PIL → rembg → Gemini → GPT

function RecRailItem({ rec, slot, onClickPlace, onDragStart, onDragEnd, onExtracted, isActive, devMode }) {
  // stepOverride is set by the server's step_used field — reflects which cascade step actually ran:
  //  -1 = served from cache, 0 = PIL, 1 = rembg, 2 = Gemini, 3 = GPT
  const [stepOverride, setStepOverride]       = useState(null);
  const [forceExtracting, setForceExtracting] = useState(false);
  const initialExtracting = rec.source === "catalog" && !rec.extractedUrl && !forceExtracting;

  const _doExtract = useCallback((forceStep, hardReset = false) => {
    if (rec.source !== "catalog" || !rec.image_url) return;
    const rawUrl = rec.image_url.startsWith("http") ? rec.image_url : `${API_BASE}${rec.image_url}`;
    const key = `${rawUrl}|${slot}`;
    _extracting.delete(key);
    _extracting.add(key);
    setForceExtracting(true);
    axios.post(
      `${API_BASE}/recommend/extract_bg`,
      {
        url: rawUrl, slot,
        product_url: rec.shop_url || null,
        source_brand: rec.brand || null,
        product_name: rec.title || null,
        force: hardReset || forceStep > 0,
        force_step: forceStep,
      },
      { headers: { ...auth(), "Content-Type": "application/json" } }
    ).then((res) => {
      if (res.data.extracted_url) {
        onExtracted(`${API_BASE}${res.data.extracted_url}`);
        if (typeof res.data.step_used === "number") setStepOverride(res.data.step_used);
      }
    }).catch(console.error).finally(() => {
      _extracting.delete(key);
      setForceExtracting(false);
    });
  }, [rec.image_url, rec.source, rec.shop_url, rec.brand, rec.title, slot, onExtracted]);

  // Initial auto-extract on mount
  useEffect(() => {
    if (rec.source !== "catalog" || !rec.image_url || rec.extractedUrl) return;
    const rawUrl = rec.image_url.startsWith("http") ? rec.image_url : `${API_BASE}${rec.image_url}`;
    const key = `${rawUrl}|${slot}`;
    if (_extracting.has(key)) return;
    _doExtract(0);
  }, [rec.image_url, rec.source, rec.extractedUrl]);

  const handleNextStep = useCallback((e) => {
    e.stopPropagation();
    // Request one step beyond what actually ran; server sets stepOverride via step_used response
    _doExtract((stepOverride ?? 0) + 1);
  }, [stepOverride, _doExtract]);

  const handleReset = useCallback((e) => {
    e.stopPropagation();
    onExtracted(null);      // clear displayed icon immediately
    setStepOverride(null);
    _doExtract(0, true);    // force-clear cache, restart from step 0
  }, [onExtracted, _doExtract]);

  const displayUrl = rec.extractedUrl || rec.icon_url || rec.image_url;
  const isLoading  = initialExtracting || forceExtracting;
  // Show ↻ only when: extraction completed (stepOverride known), was freshly extracted (not cache = -1),
  // and Gemini hasn't run yet (step < 2 means PIL=0 or rembg=1 succeeded)
  const canGoNext  = rec.source === "catalog" && stepOverride !== null && stepOverride >= 0 && stepOverride < 2;

  return (
    <div
      className={`pb-rec-rail-item${isActive ? " pb-rec-rail-item--active" : ""}`}
      draggable
      onClick={onClickPlace}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      {displayUrl ? (
        <img
          src={displayUrl}
          className="pb-rec-rail-img"
          alt=""
          style={{ opacity: isLoading ? 0.4 : 1, transition: "opacity 0.3s" }}
        />
      ) : (
        <div className="pb-rec-rail-placeholder" />
      )}
      {isLoading && <div className="pb-rec-rail-spinner" />}
      {canGoNext && (
        <button
          className="pb-rec-next-step-btn"
          disabled={isLoading}
          onClick={handleNextStep}
          title="Try next extraction method"
        >
          ↻
        </button>
      )}
      {rec.score != null && (
        <span className="pb-rec-rail-score">{Math.round(rec.score * 100)}%</span>
      )}
      {rec.source === "catalog" && rec.price && (
        <span className="pb-rec-price-tag">{rec.price}</span>
      )}
      {rec.source === "catalog" && <span className="pb-rec-catalog-dot" title="Shop item" />}
      <span className="pb-rec-rail-name">{rec.brand || rec.title || "—"}</span>
      {devMode && rec.source === "catalog" && stepOverride !== null && (
        <button
          className="pb-rec-reset-btn"
          disabled={isLoading}
          onClick={handleReset}
          title="Clear cache and re-extract from scratch"
        >✕</button>
      )}
    </div>
  );
}

// ── RailItem ──────────────────────────────────────────────────────────────────
function RailItem({ item, used, compatible, onClickPlace, onDragStart, onDragEnd, onEnter, onLeave }) {
  const displayUrl = item.icon_url || item.image_url;
  if (!displayUrl) return null;

  const zone      = inferZone(item);
  const zoneLabel = zone ? ZONE_SHORT[zone] : null;

  const cls = [
    "pb-rail-item",
    used       ? "pb-rail-item--used"       : "",
    compatible ? "pb-rail-item--compatible" : "",
  ].filter(Boolean).join(" ");

  return (
    <div
      className={cls}
      draggable
      onClick={onClickPlace}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onMouseEnter={(e) => onEnter(e, item)}
      onMouseLeave={onLeave}
      title={item.brand ? `${item.brand} · ${item.title || ""}` : item.title || ""}
    >
      <img
        src={displayUrl}
        className="pb-rail-img"
        alt=""
        style={{ opacity: item.icon_url ? 1 : 0.65 }}
      />
      {zoneLabel && <span className="pb-rail-badge">{zoneLabel}</span>}
      <span className="pb-rail-label">{item.brand || item.title || "—"}</span>
      {!item.is_mine && item.owner_initial && (
        <span className="circle-owner-badge" style={{ top: 2, left: 2 }}>
          {item.owner_initial}
        </span>
      )}
    </div>
  );
}
