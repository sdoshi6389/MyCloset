import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import axios from "axios";
import Layout from "./Layout";
import { useCircle } from "../context/CircleContext";
import "./Closet.css";

import { API_BASE as API, iconSrc, thumbSrc, photoSrc, fallbackToIcon } from "../config";
import { shrinkForUpload } from "../lib/shrinkImage";
import { matchesQuery } from "../lib/searchItems";
import { motion } from "framer-motion";

// ClosetItemCard is a sibling component, so the parent's authHeaders is
// out of scope here.
const cardAuth = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });
import { cardTint, cardTintHover, colorEdge } from "../lib/colorFamily";

const DEFAULT_CATEGORIES = ["Tops", "Bottoms", "Outerwear", "Innerwear", "Accessories", "Shoes"];

/* Head down, the way you get dressed and the way a wardrobe is arranged.
   Sorting the names alphabetically put Bottoms above Tops. */
const CATEGORY_ORDER = ["Tops", "Outerwear", "Bottoms", "Shoes", "Accessories", "Innerwear"];
const byWardrobeOrder = (a, b) => {
  const ia = CATEGORY_ORDER.indexOf(a), ib = CATEGORY_ORDER.indexOf(b);
  if (ia === -1 && ib === -1) return a.localeCompare(b);
  if (ia === -1) return 1;
  if (ib === -1) return -1;
  return ia - ib;
};

/* The attributes worth reading at a glance. These were buried in a hover
   popover that covered the next card along; the modal has room for them and is
   where someone goes when they actually want the detail. */
function itemFacts(item) {
  const clean = (v) => (typeof v === "string"
    ? v.replace(/[\[\]'"]/g, "").replace(/_/g, " ").trim()
    : Array.isArray(v) ? v.join(", ") : v);
  return [
    ["Type",      clean(item.subcategory || item.type)],
    ["Category",  clean(item.category)],
    ["Colour",    clean(item.color)],
    ["Size",      clean(item.size)],
    ["Fabric",    clean(item.fabric)],
    ["Layer",     clean(item.layering_role)],
    ["Season",    clean(item.season)],
    ["Style",     clean(item.style)],
    ["Occasion",  clean(item.occasion)],
    ["Vibe",      clean(item.vibe)],
    ["Formality", item.formality_score ? `${item.formality_score}/10` : null],
  ].filter(([, v]) => v !== null && v !== undefined && v !== "");
}

function itemKeywords(item) {
  const k = item.keywords;
  if (Array.isArray(k)) return k;
  if (typeof k === "string" && k) {
    return k.replace(/[\[\]'"]/g, "").split(",").map((x) => x.trim()).filter(Boolean);
  }
  return [];
}

function Closet() {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState(DEFAULT_CATEGORIES);
  const [files, setFiles] = useState([]);
  const [isCameraOn, setIsCameraOn] = useState(false);

  // Metadata modal state
  const [modalQueue, setModalQueue] = useState([]);
  /* Uploads the server held back because they look like something already in
     the closet. Nothing has been sent to GPT for these yet. */
  const [dupeQueue, setDupeQueue] = useState([]);
  const [activeItem, setActiveItem] = useState(null);
  const [nameInput, setNameInput] = useState("");
  const [gptBrandHint, setGptBrandHint] = useState(null);
  const [brandInput, setBrandInput] = useState("");
  const [sizeInput, setSizeInput] = useState("");
  const [categoryInput, setCategoryInput] = useState("");
  const [itemHistory, setItemHistory] = useState(null);
  const [faissMatches, setFaissMatches] = useState([]);
  const [matchPage,    setMatchPage]    = useState(0);
  const [searchText,   setSearchText]   = useState("");
  const [isSearching,  setIsSearching]  = useState(false);

  // UI state
  const [zoomedItem, setZoomedItem] = useState(null);
  const [newCatInput, setNewCatInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null); // { done, total } | null
  const [activeCategory, setActiveCategory] = useState("All");
  const [query, setQuery] = useState("");
  /* A wardrobe app's most useful question is "what am I not wearing", and the
     answer was already in the data -- wear_count and last_worn -- with nothing
     reading it. Sorting and filtering happen here rather than on the server:
     the closet is already loaded in full. */
  const [sortBy, setSortBy] = useState("added");
  const [unwornOnly, setUnwornOnly] = useState(false);
  /* Selection mode. Twenty-odd items arrived with no readable brand, and
     fixing those one modal at a time is a chore nobody completes. */
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBrand, setBulkBrand] = useState("");
  const [bulkSize, setBulkSize] = useState("");
  const [bulkCategory, setBulkCategory] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [capsule, setCapsule] = useState(null);
  const [capsuleBusy, setCapsuleBusy] = useState(false);
  const [activeSubcategory, setActiveSubcategory] = useState(null);

  const MAX_UPLOADS = 8;

  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const brandPollRef = useRef(null);
  const token = localStorage.getItem("token");
  const currentEmail = localStorage.getItem("userEmail") || "";
  const { activeCircle, setActiveCircle } = useCircle();

  useEffect(() => {
    fetchItems();
    fetchCategories();
  }, [activeCircle]);

  // Stop brand poll and camera stream on unmount
  useEffect(() => {
    return () => {
      stopBrandPoll();
      stopEmbedPoll();
      if (videoRef.current?.srcObject) {
        videoRef.current.srcObject.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  const authHeaders = () => ({ Authorization: `Bearer ${token}` });

  /* How the item has been used, fetched when it is opened rather than with the
     closet: it is one row per card and nobody reads it until they look. */
  useEffect(() => {
    if (!activeItem?.id) { setItemHistory(null); return; }
    let alive = true;
    setItemHistory(null);
    axios.get(`${API}/wear/item/${activeItem.id}/history`, { headers: authHeaders() })
      .then((r) => { if (alive) setItemHistory(r.data); })
      .catch(() => { /* the modal is useful without it */ });
    return () => { alive = false; };
  }, [activeItem?.id]);

  const fetchItems = async () => {
    try {
      const url = activeCircle
        ? `${API}/circles/${activeCircle.id}/combined-closet`
        : `${API}/get_closet_images`;
      const res = await axios.get(url, { headers: authHeaders() });
      setItems(res.data);
    } catch (err) {
      console.error("Failed to load closet items", err);
    }
  };

  const fetchCategories = async () => {
    try {
      const res = await axios.get(`${API}/categories`, { headers: authHeaders() });
      const names = [...new Set(res.data.map((c) => c.name))];
      setCategories(names);
    } catch {
      // use defaults
    }
  };

  // ── Reprocess icons via GPT ─────────────────────────────────────────────────
  const handleReprocessIcons = async () => {
    const missing = items.filter((it) => !it.icon_path).length;
    const target = missing || items.length;
    if (!window.confirm(
      `Regenerate icons for ${target} item${target === 1 ? "" : "s"}?\n\n` +
      `Each one is an image-generation call, so this costs roughly ` +
      `$${(target * 0.07).toFixed(2)} and takes several minutes.`
    )) return;
    try {
      const res = await axios.post(
        `${API}/reprocess_icons`,
        { force: false },
        { headers: { ...authHeaders(), "Content-Type": "application/json" } }
      );
      alert(res.data.message);
    } catch (e) {
      alert("Reprocess request failed — check console.");
      console.error(e);
    }
  };

  // ── Re-tag all items (GPT analysis only, no icon regen) ─────────────────────
  const handleRetagAll = async () => {
    if (!window.confirm("Re-analyze all items with GPT to fill in subcategory, layering role, and other missing metadata? Icons will NOT be regenerated. This may take a few minutes.")) return;
    try {
      const res = await axios.post(`${API}/retag_metadata`, {}, { headers: authHeaders() });
      alert(res.data.message);
    } catch (e) {
      alert("Re-tag request failed — check console.");
      console.error(e);
    }
  };

  // ── Upload ──────────────────────────────────────────────────────────────────
  const handleFileChange = (e) => {
    const selected = Array.from(e.target.files);
    setFiles(selected.slice(0, MAX_UPLOADS));
  };

  const handleUpload = async () => {
    if (!files.length) return;
    const toUpload = files.slice(0, MAX_UPLOADS);
    setUploading(true);
    setUploadProgress({ done: 0, total: toUpload.length });

    // Indexed slots preserve the original file selection order regardless of
    // which parallel upload finishes first.
    const slots = new Array(toUpload.length).fill(null);
    const failedNames = [];
    const pendingDupes = [];

    await Promise.all(
      toUpload.map(async (file, idx) => {
        const formData = new FormData();
        // Shrink before it goes on the wire. The server caps stored photos at
        // the same size regardless, so this only decides whether 28 MB or
        // 1.4 MB makes the trip -- and the trip is now the slow part.
        formData.append("files", await shrinkForUpload(file));
        try {
          const res = await axios.post(`${API}/upload_closet_images`, formData, {
            headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
          });
          const returned = res.data.items || [];
          const dupes = res.data.duplicates || {};
          if (returned.length) {
            const match = dupes[returned[0].filename];
            if (match) pendingDupes.push({ item: returned[0], match });
            slots[idx] = returned[0];
            // Card appears immediately as each upload finishes
            setItems((prev) =>
              prev.some((p) => p.id === returned[0].id) ? prev : [...prev, returned[0]]
            );
          }
        } catch (err) {
          console.error(`Upload failed for ${file.name}:`, err);
          failedNames.push(file.name);
        } finally {
          setUploadProgress((prev) => prev ? { ...prev, done: prev.done + 1 } : null);
        }
      })
    );

    const uploaded = slots.filter(Boolean);
    setFiles([]);
    setUploading(false);
    setUploadProgress(null);

    if (failedNames.length) {
      alert(`${failedNames.length} file(s) failed to upload:\n${failedNames.join("\n")}`);
    }

    if (!uploaded.length) return;

    // Ask about the possible duplicates first: those are the only ones whose
    // processing is still on hold, so a decision there decides what happens.
    if (pendingDupes.length) {
      setDupeQueue(pendingDupes);
      setItems((prev) => {
        const seen = new Set(prev.map((i) => i.id));
        return [...prev, ...uploaded.filter((i) => !seen.has(i.id))];
      });
      return;
    }

    // Refresh all items once — picks up any AI data that already ran during
    // the parallel uploads, and gives cards their GPT names before modal opens.
    try {
      const freshRes = await axios.get(`${API}/get_closet_images`, { headers: authHeaders() });
      const byFilename = Object.fromEntries(freshRes.data.map((i) => [i.filename, i]));
      setItems(freshRes.data);
      // Keep original order; fall back to upload-time data if not found yet
      const ordered = uploaded.map((i) => byFilename[i.filename] || i);
      startModalQueue(ordered);
    } catch {
      startModalQueue(uploaded);
    }
  };

  /* Keep it: release the processing the server held, and carry on into the
     normal metadata modal. Drop it: delete the row and the photo with it. */
  const resolveDupe = async (keep) => {
    const [current, ...rest] = dupeQueue;
    if (!current) return;
    try {
      if (keep) {
        await axios.post(`${API}/closet/confirm_upload`,
                         { filename: current.item.filename },
                         { headers: authHeaders() });
      } else {
        await axios.delete(`${API}/delete_closet_image`, {
          headers: authHeaders(),
          params: { filename: current.item.filename },
        });
        setItems((prev) => prev.filter((i) => i.id !== current.item.id));
      }
    } catch (e) {
      console.error("Could not resolve that upload:", e);
    }
    setDupeQueue(rest);
    if (!rest.length) {
      try {
        const fresh = await axios.get(`${API}/get_closet_images`, { headers: authHeaders() });
        setItems(fresh.data);
      } catch { /* the list will catch up on the next load */ }
    }
  };

  // ── Modal queue ──────────────────────────────────────────────────────────────
  const stopBrandPoll = () => {
    if (brandPollRef.current) {
      clearInterval(brandPollRef.current);
      brandPollRef.current = null;
    }
  };

  const embedPollRef = useRef(null);

  const stopEmbedPoll = () => {
    if (embedPollRef.current) {
      clearInterval(embedPollRef.current);
      embedPollRef.current = null;
    }
  };

  /* Opening Edit froze a copy of the item, so an embedding that finished after
     the closet list loaded never reached the open modal and Find Match stayed
     hidden until the card was closed and reopened. This refreshes just that
     flag -- deliberately not the brand/name inputs, which the user may be
     editing. */
  const startEmbedPoll = (filename) => {
    stopEmbedPoll();
    let attempts = 0;
    embedPollRef.current = setInterval(async () => {
      attempts++;
      if (attempts > 40) { stopEmbedPoll(); return; }
      try {
        const res = await axios.get(`${API}/get_closet_images`, { headers: authHeaders() });
        const updated = res.data.find((i) => i.filename === filename);
        if (!updated) return;
        setItems((prev) => prev.map((i) => i.filename === filename ? { ...i, ...updated } : i));
        if (updated.has_embedding) {
          setActiveItem((prev) =>
            prev?.filename === filename ? { ...prev, has_embedding: true } : prev
          );
          stopEmbedPoll();
        }
      } catch {
        /* transient - keep polling until the attempt cap */
      }
    }, 3000);
  };

  const startBrandPoll = (filename) => {
    stopBrandPoll();
    let attempts = 0;
    brandPollRef.current = setInterval(async () => {
      attempts++;
      if (attempts > 40) { stopBrandPoll(); return; }
      try {
        const res = await axios.get(`${API}/get_closet_images`, { headers: authHeaders() });
        const updated = res.data.find((i) => i.filename === filename);
        if (!updated) return;

        // Update the closet grid card live as GPT data arrives
        setItems((prev) => prev.map((i) => i.filename === filename ? { ...i, ...updated } : i));

        // Push has_embedding into the open modal so Find Match appears the
        // moment the CLIP embedding finishes — no save/re-edit needed
        setActiveItem((prev) =>
          prev?.filename === filename ? { ...prev, has_embedding: updated.has_embedding } : prev
        );

        if (updated.brand) {
          setBrandInput(updated.brand);
          setGptBrandHint(updated.brand);
        }
        const detectedName = updated.matched_title || updated.caption || null;
        if (detectedName) {
          setNameInput((prev) => prev || detectedName);
        }
        // Keep polling until brand, name, AND embedding are all ready
        if (updated.brand && detectedName && updated.has_embedding) stopBrandPoll();
      } catch { /* ignore poll errors */ }
    }, 2000);
  };

  const startModalQueue = (queue) => {
    const [first, ...rest] = queue;
    setActiveItem(first);
    const brand = first.brand || first.tag_text || "";
    const name  = first.matched_title || first.caption || "";
    setNameInput(name);
    setGptBrandHint(first.brand || null);
    setBrandInput(brand);
    setSizeInput(first.size || "");
    setCategoryInput(first.category || "");
    setModalQueue(rest);
    setFaissMatches([]);
    // Poll until GPT fills in brand and/or name (pipeline runs in background)
    if (!brand || !name) startBrandPoll(first.filename);
  };

  const proceedToNextModal = async () => {
    stopBrandPoll();
    stopEmbedPoll();
    if (modalQueue.length) {
      const [next, ...rest] = modalQueue;
      // Refresh the next item before showing its modal so GPT data that ran
      // while the previous modal was open is shown immediately, not discovered
      // mid-poll after the user has already started reading the modal.
      let freshNext = next;
      try {
        const res = await axios.get(`${API}/get_closet_images`, { headers: authHeaders() });
        setItems(res.data);
        freshNext = res.data.find((i) => i.filename === next.filename) || next;
      } catch { /* use stale data */ }
      startModalQueue([freshNext, ...rest]);
    } else {
      setActiveItem(null);
      fetchItems();
    }
  };

  const saveCategory = async (item, category) => {
    if (category && item?.id) {
      await axios.post(
        `${API}/update_closet_item_category`,
        { item_id: item.id, category },
        { headers: { ...authHeaders(), "Content-Type": "application/json" } }
      );
    }
  };

  // Save only — no FAISS
  const handleSave = async () => {
    if (!activeItem) return;
    try {
      await axios.post(
        `${API}/update_closet_metadata`,
        { filename: activeItem.filename, name: nameInput, brand: brandInput, size: sizeInput, save_only: true },
        { headers: { ...authHeaders(), "Content-Type": "application/json" } }
      );
      await saveCategory(activeItem, categoryInput);
      proceedToNextModal();
    } catch (err) {
      console.error("Failed to save metadata", err);
      proceedToNextModal();
    }
  };

  // Save + run FAISS match
  const handleFindMatch = async () => {
    if (!activeItem) return;
    try {
      const res = await axios.post(
        `${API}/update_closet_metadata`,
        { filename: activeItem.filename, name: nameInput, brand: brandInput, size: sizeInput },
        { headers: { ...authHeaders(), "Content-Type": "application/json" } }
      );
      await saveCategory(activeItem, categoryInput);
      if (res.data.matches?.length > 0) {
        setFaissMatches(res.data.matches);
        setMatchPage(0);
        setSearchText("");
      } else {
        alert("No similar products found in the database.");
        proceedToNextModal();
      }
    } catch (err) {
      console.error("Failed to find match", err);
      proceedToNextModal();
    }
  };

  const handleTextSearch = async () => {
    if (!activeItem || !searchText.trim()) return;
    setIsSearching(true);
    try {
      const res = await axios.post(
        `${API}/faiss_text_search`,
        { filename: activeItem.filename, search_text: searchText.trim(), brand: brandInput || null },
        { headers: { ...authHeaders(), "Content-Type": "application/json" } }
      );
      if (res.data.matches?.length > 0) {
        setFaissMatches(res.data.matches);
        setMatchPage(0);
      } else {
        alert("No matches found for that search.");
      }
    } catch (err) {
      console.error("Text search failed", err);
    } finally {
      setIsSearching(false);
    }
  };

  const handleMatchSelect = async (match) => {
    if (!activeItem) return;
    try {
      await axios.post(
        `${API}/save_match_selection`,
        { filename: activeItem.filename, matched_brand: match.source, matched_title: match.title },
        { headers: { ...authHeaders(), "Content-Type": "application/json" } }
      );
    } catch (err) {
      console.error("Failed to save match", err);
    } finally {
      setFaissMatches([]);
      proceedToNextModal();
    }
  };

  const handleDelete = async (item) => {
    if (!window.confirm(`Delete "${item.filename}"?`)) return;
    try {
      await axios.delete(`${API}/delete_closet_image`, {
        params: { filename: item.filename },
        headers: authHeaders(),
      });
      fetchItems();
    } catch {
      alert("Delete failed.");
    }
  };

  // ── Custom category ──────────────────────────────────────────────────────────
  const addCustomCategory = async () => {
    const name = newCatInput.trim();
    if (!name) return;
    try {
      await axios.post(`${API}/categories`, { name }, { headers: { ...authHeaders(), "Content-Type": "application/json" } });
    } catch { /* ok if already exists */ }
    setCategories((prev) => [...new Set([...prev, name])]);
    setNewCatInput("");
  };

  // ── Camera ───────────────────────────────────────────────────────────────────
  const startCamera = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      alert("Camera not supported on this browser/connection.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      videoRef.current.srcObject = stream;
      videoRef.current.play();
      setIsCameraOn(true);
    } catch (err) {
      if (err.name === "NotAllowedError") {
        alert("Camera permission denied.\n\nFix: click the camera icon in your browser address bar → Allow → then try again.");
      } else if (err.name === "NotFoundError") {
        alert("No camera found on this device.");
      } else {
        alert(`Camera error: ${err.message}`);
      }
    }
  };

  const stopCamera = () => {
    if (videoRef.current?.srcObject) {
      videoRef.current.srcObject.getTracks().forEach((t) => t.stop());
      videoRef.current.srcObject = null;
    }
    setIsCameraOn(false);
  };

  const captureAndUpload = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    canvas.toBlob(async (blob) => {
      const fd = new FormData();
      fd.append("files", blob, "webcam.jpg");
      try {
        setUploading(true);
        const res = await axios.post(`${API}/upload_closet_images`, fd, {
          headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
        });
        stopCamera();
        // Go through the metadata modal the same as file upload
        const returned = res.data?.items || [];
        if (returned.length) {
          try {
            const freshRes = await axios.get(`${API}/get_closet_images`, { headers: authHeaders() });
            const byFilename = Object.fromEntries(freshRes.data.map((i) => [i.filename, i]));
            setItems(freshRes.data);
            const ordered = returned.map((i) => byFilename[i.filename] || i);
            startModalQueue(ordered);
          } catch {
            startModalQueue(returned);
          }
        } else {
          fetchItems();
        }
      } catch (err) {
        console.error("Webcam upload failed:", err);
        alert("Failed to upload webcam capture.");
      } finally {
        setUploading(false);
      }
    }, "image/jpeg");
  };

  // ── Derived: grouped items ───────────────────────────────────────────────────
  // Available subcategories for the currently selected category
  const availableSubcategories = activeCategory !== "All"
    ? [...new Set(
        items
          .filter((it) => it.category === activeCategory && it.subcategory)
          .map((it) => it.subcategory)
      )].sort()
    : [];

  const toggleSelected = (id) => setSelected((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const applyBulk = async () => {
    if (!selected.size || bulkBusy) return;
    const payload = { ids: [...selected] };
    // Only send a field that was actually typed into, so blanks do not wipe
    // values on items the change was not meant for.
    if (bulkBrand.trim()) payload.brand = bulkBrand.trim();
    if (bulkSize.trim()) payload.size = bulkSize.trim();
    if (bulkCategory) payload.category = bulkCategory;
    if (Object.keys(payload).length === 1) return;

    setBulkBusy(true);
    try {
      const { data } = await axios.post(`${API}/closet/bulk_update`, payload,
                                        { headers: authHeaders() });
      const byId = Object.fromEntries((data.items || []).map((i) => [i.id, i]));
      setItems((prev) => prev.map((i) => (byId[i.id] ? { ...i, ...byId[i.id] } : i)));
      setBulkBrand(""); setBulkSize(""); setBulkCategory("");
      setSelected(new Set());
      setSelectMode(false);
    } catch (e) {
      console.error("Bulk update failed:", e);
      alert(e?.response?.data?.message || "Could not update those items.");
    } finally {
      setBulkBusy(false);
    }
  };

  /* "If I pack only these, what can I actually wear?" -- the same assembly the
     recommender does, over the chosen items only. */
  const askCapsule = async () => {
    if (selected.size < 2 || capsuleBusy) return;
    setCapsuleBusy(true);
    try {
      const { data } = await axios.post(`${API}/suggestions/capsule`,
                                        { ids: [...selected] },
                                        { headers: authHeaders() });
      setCapsule(data);
    } catch (e) {
      alert(e?.response?.data?.message || "Could not work that out.");
    } finally {
      setCapsuleBusy(false);
    }
  };

  const daysSince = (iso) => {
    if (!iso) return Infinity;           // never worn sorts as longest ago
    const d = (Date.now() - new Date(iso).getTime()) / 86400000;
    return Number.isFinite(d) ? d : Infinity;
  };

  let searched = query ? items.filter((it) => matchesQuery(it, query)) : items;
  if (unwornOnly) searched = searched.filter((it) => !(it.wear_count > 0));
  if (sortBy !== "added") {
    searched = [...searched].sort((a, b) => {
      if (sortBy === "least") return (a.wear_count || 0) - (b.wear_count || 0);
      if (sortBy === "stale") return daysSince(b.last_worn) - daysSince(a.last_worn);
      if (sortBy === "name") {
        return (a.matched_title || a.caption || "").localeCompare(b.matched_title || b.caption || "");
      }
      return 0;
    });
  }

  const grouped = {};
  (activeCategory === "All"
    ? [...[...categories].sort(byWardrobeOrder), "Uncategorized"]
    : [activeCategory]).forEach((cat) => {
    let group = searched.filter((it) =>
      cat === "Uncategorized"
        ? !it.category || !categories.includes(it.category)
        : it.category === cat
    );
    // Drill down by subcategory if one is selected
    if (activeSubcategory && cat !== "Uncategorized") {
      group = group.filter((it) => it.subcategory === activeSubcategory);
    }
    if (group.length) grouped[cat] = group;
  });

  return (
    <Layout>
      <h1 className="page-heading">{activeCircle ? `${activeCircle.name} — Closet` : "Your Closet"}</h1>

      {activeCircle && (
        <div className="circle-context-banner">
          <span>Viewing circle: <strong>{activeCircle.name}</strong> — all members' items</span>
          <button onClick={() => setActiveCircle(null)}>Back to Just Me</button>
        </div>
      )}

      {/* ── Upload bar — hidden in circle mode ──────────────────────────────── */}
      {!activeCircle && <div className="closet-upload-bar section-card">
        <label className="upload-file-label">
          <input
            type="file"
            accept="image/*,.heic,.heif"
            multiple
            onChange={handleFileChange}
            style={{ display: "none" }}
          />
          📁 {files.length
            ? `${files.length} file${files.length > 1 ? "s" : ""} selected`
            : `Choose files (max ${MAX_UPLOADS})`}
        </label>
        <button className="btn-primary" onClick={handleUpload} disabled={uploading || !files.length}>
          {uploading && uploadProgress
            ? `Uploading ${uploadProgress.done}/${uploadProgress.total}…`
            : uploading ? "Uploading…" : "Upload"}
        </button>
        <button className="btn-secondary" onClick={!isCameraOn ? startCamera : captureAndUpload}>
          {!isCameraOn ? "📷 Camera" : "📸 Capture"}
        </button>
        {isCameraOn && (
          <button className="btn-secondary" onClick={stopCamera} style={{ fontSize: "0.78rem" }}>
            ✕ Stop camera
          </button>
        )}
        <button className="btn-secondary" onClick={handleRetagAll} style={{ marginLeft: "auto", fontSize: "0.78rem" }}>
          ✦ Re-tag All
        </button>
        <button className="btn-secondary" onClick={handleReprocessIcons} style={{ fontSize: "0.78rem" }}>
          ✦ Regenerate Icons
        </button>
        {isCameraOn && (
          <>
            <video ref={videoRef} autoPlay className="closet-camera-preview" />
            <canvas ref={canvasRef} style={{ display: "none" }} />
          </>
        )}
      </div>}

      {/* ── Category filter tabs ────────────────────────────────────────────── */}
      <div className="closet-cat-tabs">
        <div className="closet-search">
          <input
            className="closet-search-input"
            type="search"
            value={query}
            placeholder="Search by name, brand, colour…"
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search your closet"
          />
          {query && (
            <span className="closet-search-count">
              {Object.values(grouped).reduce((n, g) => n + g.length, 0)} of {items.length}
            </span>
          )}
        </div>
        <button className={`closet-cat-tab${selectMode ? " active" : ""}`}
                onClick={() => { setSelectMode((v) => !v); setSelected(new Set()); }}
                title="Pick several items and change them together">
          {selectMode ? "Done" : "Select"}
        </button>
        <select className="closet-sort" value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                aria-label="Sort your closet">
          <option value="added">Recently added</option>
          <option value="least">Least worn</option>
          <option value="stale">Longest unworn</option>
          <option value="name">Name A–Z</option>
        </select>
        <button className={`closet-cat-tab closet-unworn${unwornOnly ? " active" : ""}`}
                onClick={() => setUnwornOnly((v) => !v)}
                title="Only items you have never worn">
          Never worn
          <span className="closet-unworn-count">
            {items.filter((it) => !(it.wear_count > 0)).length}
          </span>
        </button>
        {["All", ...[...categories].sort(byWardrobeOrder)]
          .filter((cat) => cat === "All" || cat === activeCategory
                        || items.some((it) => it.category === cat))
          .map((cat) => (
          <button
            key={cat}
            className={`closet-cat-tab${activeCategory === cat ? " active" : ""}`}
            onClick={() => { setActiveCategory(cat); setActiveSubcategory(null); }}
          >
            {cat}
          </button>
        ))}
        <div className="closet-add-cat">
          <input
            placeholder="+ New category"
            value={newCatInput}
            onChange={(e) => setNewCatInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCustomCategory()}
            className="field-input"
            style={{ width: 140, padding: "6px 10px" }}
          />
          <button className="btn-secondary" onClick={addCustomCategory} style={{ padding: "6px 10px" }}>
            Add
          </button>
        </div>
      </div>

      {/* ── Subcategory pills (only when a specific category is active) ──────── */}
      {availableSubcategories.length > 0 && (
        <div className="closet-subcat-tabs">
          <button
            className={`closet-subcat-tab${!activeSubcategory ? " active" : ""}`}
            onClick={() => setActiveSubcategory(null)}
          >
            All {activeCategory}
          </button>
          {availableSubcategories.map((sub) => (
            <button
              key={sub}
              className={`closet-subcat-tab${activeSubcategory === sub ? " active" : ""}`}
              onClick={() => setActiveSubcategory(sub)}
            >
              {sub.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      )}

      {/* ── Items grouped by category ───────────────────────────────────────── */}
      {Object.entries(grouped).map(([cat, catItems]) => (
        <section key={cat} className="closet-category-section">
          <h2 className="closet-category-heading">{cat}</h2>
          <div className="closet-grid">
            {catItems.map((item, index) => {
              const ownedByMe = !item.owner_email || item.owner_email === currentEmail;
              return (
                <ClosetItemCard
                  key={item.id}
                  item={item}
                  index={index}
                  ownedByMe={ownedByMe}
                  ownerInitial={item.owner_initial}
                  selectMode={selectMode}
                  isSelected={selected.has(item.id)}
                  onToggleSelect={() => toggleSelected(item.id)}
                  onZoom={() => setZoomedItem(item)}
                  onEdit={ownedByMe ? () => {
                    // Use the freshest copy from state, not the closure's snapshot
                    const live = items.find((i) => i.id === item.id) || item;
                    setActiveItem(live);
                    if (!live.has_embedding) startEmbedPoll(live.filename);
                    setNameInput(item.matched_title || item.caption || "");
                    setGptBrandHint(item.brand || null);
                    setBrandInput(item.brand || item.tag_text || "");
                    setSizeInput(item.size || "");
                    setCategoryInput(item.category || "");
                    setModalQueue([]);
                    setFaissMatches([]);
                  } : null}
                  onDelete={ownedByMe ? () => handleDelete(item) : null}
                />
              );
            })}
          </div>
        </section>
      ))}

      {!items.length && (
        <div className="closet-empty">
          <p>Your closet is empty. Upload some clothing items to get started!</p>
        </div>
      )}

      {/* ── Possible duplicate ──────────────────────────────────────────────── */}
      {dupeQueue.length > 0 && (() => {
        const { item, match } = dupeQueue[0];
        return (
          <div className="modal-overlay">
            <div className="modal-box dupe-box" onClick={(e) => e.stopPropagation()}>
              <h3>
                Already in your closet?
                {dupeQueue.length > 1 && (
                  <span style={{ fontSize: "0.75rem", color: "#8080a8", marginLeft: 10 }}>
                    {dupeQueue.length - 1} more after this
                  </span>
                )}
              </h3>
              <p className="dupe-lead">
                This photo closely matches a piece you already have. Nothing has
                been processed yet — is it the same thing?
              </p>
              <div className="dupe-pair">
                <figure className="dupe-side">
                  <img src={photoSrc(item.url)} alt="" />
                  <figcaption>
                    <span className="dupe-tag">Just uploaded</span>
                    <span className="dupe-name">{item.filename}</span>
                  </figcaption>
                </figure>
                <span className="dupe-vs">{Math.round(match.similarity * 100)}% alike</span>
                <figure className="dupe-side">
                  <img src={match.thumb_url || match.icon_url || photoSrc(match.url)}
                       alt=""
                       onError={(e) => {
                         const img = e.currentTarget;
                         if (img.dataset.fellBack) return;
                         img.dataset.fellBack = "1";
                         img.src = photoSrc(match.url);
                       }} />
                  <figcaption>
                    <span className="dupe-tag">Already in your closet</span>
                    <span className="dupe-name">{match.title}</span>
                    {match.brand && <span className="dupe-brand">{match.brand}</span>}
                  </figcaption>
                </figure>
              </div>
              <div className="dupe-actions">
                <button className="dupe-btn dupe-btn--primary" onClick={() => resolveDupe(true)}>
                  It&apos;s a different piece — add it
                </button>
                <button className="dupe-btn" onClick={() => resolveDupe(false)}>
                  Already have it — remove this
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── Bulk edit bar ───────────────────────────────────────────────────── */}
      {selectMode && (
        <div className="bulk-bar">
          <span className="bulk-count">
            {selected.size} selected
          </span>
          <button className="bulk-link"
                  onClick={() => setSelected(new Set(
                    Object.values(grouped).flat().map((i) => i.id)))}>
            Select all shown
          </button>
          <button className="bulk-link" onClick={() => setSelected(new Set())}>Clear</button>

          <input className="bulk-input" placeholder="Brand" value={bulkBrand}
                 onChange={(e) => setBulkBrand(e.target.value)} />
          <input className="bulk-input bulk-input--sm" placeholder="Size" value={bulkSize}
                 onChange={(e) => setBulkSize(e.target.value)} />
          <select className="bulk-input bulk-input--sm" value={bulkCategory}
                  onChange={(e) => setBulkCategory(e.target.value)}>
            <option value="">Category</option>
            {categories.map((c) => <option key={c}>{c}</option>)}
          </select>

          <button className="btn-primary bulk-apply"
                  disabled={!selected.size || bulkBusy
                            || !(bulkBrand.trim() || bulkSize.trim() || bulkCategory)}
                  onClick={applyBulk}>
            {bulkBusy ? "Applying…" : `Apply to ${selected.size}`}
          </button>
          <button className="btn-secondary bulk-apply"
                  disabled={selected.size < 2 || capsuleBusy}
                  onClick={askCapsule}
                  title="How many outfits do these make?">
            {capsuleBusy ? "Working…" : "What can I wear?"}
          </button>
        </div>
      )}

      {/* ── Capsule result ──────────────────────────────────────────────────── */}
      {capsule && (
        <div className="modal-overlay" onClick={() => setCapsule(null)}>
          <div className="modal-box capsule-box" onClick={(e) => e.stopPropagation()}>
            <h3 className="im-title">
              {capsule.picked} pieces make {capsule.total} outfit
              {capsule.total === 1 ? "" : "s"}
            </h3>
            <p className="capsule-sub">
              {capsule.total === 0
                ? "Not enough to build a full look — you need a top and a bottom at least."
                : capsule.unused?.length
                  ? `${capsule.unused.length} of them never made it into a look.`
                  : "Every piece earns its place."}
            </p>
            <div className="capsule-grid">
              {(capsule.outfits || []).map((look, i) => (
                <div className="capsule-look" key={i}>
                  {Object.entries(look.items || {}).map(([slot, it]) => (
                    <img key={slot} src={it.thumb_url || it.icon_url || it.image_url}
                         alt={it.title || ""} loading="lazy" />
                  ))}
                </div>
              ))}
            </div>
            <div className="modal-action-row">
              <button className="btn-secondary" style={{ marginLeft: "auto" }}
                      onClick={() => setCapsule(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Metadata modal ──────────────────────────────────────────────────── */}
      {activeItem && !faissMatches.length && (
        <div className="modal-overlay" onClick={() => { stopBrandPoll(); stopEmbedPoll(); setActiveItem(null); }}>
          <div className="modal-box item-modal" onClick={(e) => e.stopPropagation()}>
            <div className="im-head">
              <h3 className="im-title">
                {activeItem.matched_title || activeItem.caption || activeItem.filename}
              </h3>
              <div className="im-sub">
                {activeItem.brand && <span className="im-brand">{activeItem.brand}</span>}
                <span className="im-file">{activeItem.filename}</span>
                {modalQueue.length > 0 && (
                  <span className="im-queue">{modalQueue.length} more after this</span>
                )}
              </div>
            </div>

            <div className="im-body">
              <div className="im-left">
                {activeItem.icon_path && (
                  <img src={iconSrc(activeItem.icon_path)} alt="" className="im-icon" />
                )}
                <div className="im-stats">
                  <span className={`im-stat${(itemHistory?.in_laundry ?? activeItem.in_laundry) ? " im-stat--on" : ""}`}>
                    {(itemHistory?.in_laundry ?? activeItem.in_laundry) ? "In the wash" : "Clean"}
                  </span>
                  <span className="im-stat">
                    Worn {itemHistory?.wear_count ?? activeItem.wear_count ?? 0}&times;
                  </span>
                  {(itemHistory?.last_worn || activeItem.last_worn) && (
                    <span className="im-stat">
                      Last {new Date(itemHistory?.last_worn || activeItem.last_worn).toLocaleDateString()}
                    </span>
                  )}
                </div>
                {itemFacts(activeItem).length > 0 && (
                  <dl className="im-facts">
                    {itemFacts(activeItem).map(([k, v]) => (
                      <div className="im-fact" key={k}>
                        <dt>{k}</dt>
                        <dd>{v}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {itemKeywords(activeItem).length > 0 && (
                  <div className="im-keywords">
                    {itemKeywords(activeItem).slice(0, 10).map((k, i) => (
                      <span className="im-keyword" key={i}>{k}</span>
                    ))}
                  </div>
                )}

                {(itemHistory?.paired_with?.length > 0
                  || itemHistory?.in_outfits?.length > 0) && (
                  <div className="im-history">
                    {itemHistory.paired_with?.length > 0 && (
                      <>
                        <h4 className="im-history-title">Usually worn with</h4>
                        <div className="im-pairs">
                          {itemHistory.paired_with.map((p) => (
                            <div className="im-pair" key={p.id} title={`${p.title} · ${p.times}x`}>
                              {p.thumb_url
                                ? <img src={p.thumb_url} alt="" loading="lazy" />
                                : <span className="im-pair-blank" />}
                              <span className="im-pair-times">{p.times}&times;</span>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                    {itemHistory.in_outfits?.length > 0 && (
                      <p className="im-history-note">
                        In {itemHistory.in_outfits.length} saved look
                        {itemHistory.in_outfits.length === 1 ? "" : "s"}
                        {": "}
                        {itemHistory.in_outfits.slice(0, 3).map((o) => o.name).join(", ")}
                      </p>
                    )}
                  </div>
                )}
              </div>

              <div className="im-right">
            <div className="field-group">
              <label className="field-label">Name</label>
              <input className="field-input" value={nameInput} onChange={(e) => setNameInput(e.target.value)} placeholder="e.g. Ripstop Trackpant" />
            </div>
            <div className="field-group">
              <label className="field-label">
                Brand
                {activeItem.tag_text && (
                  <span style={{ color: "#c9b8ff", marginLeft: 8, fontWeight: 400 }}>
                    OCR: {activeItem.tag_text}
                  </span>
                )}
                {gptBrandHint && (
                  <span style={{ color: "#90e080", marginLeft: 8, fontWeight: 400 }}>
                    GPT: {gptBrandHint}
                  </span>
                )}
              </label>
              <input className="field-input" value={brandInput} onChange={(e) => setBrandInput(e.target.value)} placeholder="e.g. Gymshark" />
            </div>
            <div className="field-group">
              <label className="field-label">Size</label>
              <input className="field-input" value={sizeInput} onChange={(e) => setSizeInput(e.target.value)} placeholder="e.g. M, 32, XL" />
            </div>
            <div className="field-group">
              <label className="field-label">Category</label>
              <select className="field-select" value={categoryInput} onChange={(e) => setCategoryInput(e.target.value)}>
                <option value="">— select —</option>
                {categories.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>

                <div className="modal-action-row">
                  <button className="btn-primary" onClick={handleSave}>Save</button>
                  {activeItem.has_embedding && (
                    <button className="btn-secondary" onClick={handleFindMatch}>Find Match</button>
                  )}
                  <button className="btn-secondary"
                          onClick={() => { stopBrandPoll(); setActiveItem(null); }}
                          style={{ marginLeft: "auto" }}>Cancel</button>
                </div>
                <p className="modal-action-hint">
                  {activeItem.has_embedding
                    ? <><strong>Find Match</strong> searches the product database for a similar item.</>
                    : <>Product matching becomes available once the AI finishes processing this item.</>
                  }
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── FAISS match selector ─────────────────────────────────────────────── */}
      {faissMatches.length > 0 && (() => {
        const PAGE_SIZE = 5;
        const pageMatches = faissMatches.slice(matchPage * PAGE_SIZE, (matchPage + 1) * PAGE_SIZE);
        const hasNext = (matchPage + 1) * PAGE_SIZE < faissMatches.length;
        const totalPages = Math.ceil(faissMatches.length / PAGE_SIZE);
        return (
          <div className="modal-overlay" onClick={() => { setFaissMatches([]); proceedToNextModal(); }}>
            <div className="modal-box match-modal" onClick={(e) => e.stopPropagation()}>
              <h3>Similar products — pick the best match</h3>
              <div className="match-search-row">
                <input
                  className="field-input"
                  placeholder='Refine search (e.g. "Splendor Bra white")'
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleTextSearch()}
                />
                <button
                  className="btn-secondary"
                  onClick={handleTextSearch}
                  disabled={isSearching || !searchText.trim()}
                >
                  {isSearching ? "Searching…" : "Search"}
                </button>
              </div>
              {totalPages > 1 && (
                <p className="match-page-indicator">{matchPage + 1} / {totalPages}</p>
              )}
              <div className="match-grid">
                {pageMatches.map((match, idx) => (
                  <div key={idx} className="match-card" onClick={() => handleMatchSelect(match)}>
                    <img src={match.image} alt={match.title} />
                    <div className="match-info">
                      <p className="match-title">{match.title}</p>
                      <p className="match-meta">{match.price} · {match.color}</p>
                      <p className="match-source">{match.source}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="match-footer">
                <button className="btn-secondary" onClick={() => { setFaissMatches([]); proceedToNextModal(); }}>
                  Skip
                </button>
                {matchPage > 0 && (
                  <button className="btn-secondary" onClick={() => setMatchPage(p => p - 1)}>
                    ← Back
                  </button>
                )}
                {hasNext && (
                  <button className="btn-primary" onClick={() => setMatchPage(p => p + 1)}>
                    Next →
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── Zoom modal ──────────────────────────────────────────────────────── */}
      {zoomedItem && (
        <div className="modal-overlay" onClick={() => setZoomedItem(null)}>
          <img
            src={photoSrc(zoomedItem.url)}
            alt="Zoom"
            style={{ maxHeight: "90vh", maxWidth: "90vw", borderRadius: 12 }}
          />
        </div>
      )}
    </Layout>
  );
}

function iconFilename(iconPath) {
  if (!iconPath) return null;
  return iconPath.split(/[/\\]/).pop();
}

function ClosetItemCard({ item, index = 0, ownedByMe, ownerInitial, onZoom, onEdit, onDelete,
                         selectMode = false, isSelected = false, onToggleSelect }) {
  const [hovered, setHovered] = useState(false);
  const [hoverPos, setHoverPos] = useState(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const cardRef = useRef(null);

  // Wear state is echoed locally so the badge and laundry toggle react at once;
  // the request reconciles in the background and reverts if it fails.
  const [wearCount, setWearCount] = useState(item.wear_count || 0);
  const [inLaundry, setInLaundry] = useState(Boolean(item.in_laundry));
  const [wearBusy, setWearBusy]   = useState(false);
  const [menuOpen, setMenuOpen]   = useState(false);
  const [lastWorn, setLastWorn]   = useState(item.last_worn || null);

  useEffect(() => { setWearCount(item.wear_count || 0); }, [item.wear_count]);
  useEffect(() => { setInLaundry(Boolean(item.in_laundry)); }, [item.in_laundry]);

  const toggleLaundry = async (e) => {
    e.stopPropagation();
    if (wearBusy) return;
    const next = !inLaundry;
    setInLaundry(next);
    setWearBusy(true);
    try {
      await axios.post(`${API}/wear/item/${item.id}/laundry`,
                       { in_laundry: next }, { headers: cardAuth() });
    } catch {
      setInLaundry(!next);            // put it back; nothing was saved
    } finally {
      setWearBusy(false);
    }
  };

  const markWorn = async (e) => {
    e.stopPropagation();
    if (wearBusy) return;
    setWearCount((c) => c + 1);
    setWearBusy(true);
    try {
      const r = await axios.post(`${API}/wear/item/${item.id}/worn`, {},
                                 { headers: cardAuth() });
      if (typeof r.data?.wear_count === "number") setWearCount(r.data.wear_count);
      if (r.data?.last_worn) setLastWorn(r.data.last_worn);
    } catch {
      setWearCount((c) => Math.max(0, c - 1));
    } finally {
      setWearBusy(false);
    }
  };

  const iconUrl  = iconSrc(item.icon_path);
  const thumbUrl = thumbSrc(item.icon_path);

  const hasGptData = !!(item.caption || item.type || item.color || item.style ||
    item.season || item.fabric || item.vibe || item.gender || item.keywords);

  const handleMouseEnter = () => {
    if (cardRef.current && hasGptData) {
      const rect = cardRef.current.getBoundingClientRect();
      const CARD_W = 260;
      const spaceRight = window.innerWidth - rect.right;
      const x = spaceRight >= CARD_W + 16 ? rect.right + 12 : rect.left - CARD_W - 12;
      setHoverPos({ x: Math.max(4, x), y: rect.top });
    }
    setHovered(true);
  };

  return (
    <motion.div
      ref={cardRef}
      className={`closet-card${selectMode ? " closet-card--picking" : ""}${isSelected ? " closet-card--picked" : ""}`}
      style={{
        "--card-tint": cardTint(item.color),
        "--card-tint-hover": cardTintHover(item.color),
        "--card-edge": colorEdge(item.color),
      }}
      initial={{ opacity: 0, y: 28, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.62, ease: [0.22, 1, 0.36, 1], delay: Math.min(index * 0.05, 0.7) }}
      whileHover={{ y: -8, transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] } }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => { setHovered(false); setHoverPos(null); setMenuOpen(false); }}
    >
      <div className={`closet-card-image${imgLoaded ? "" : " closet-card-image--loading"}`}
           onClick={selectMode ? onToggleSelect : onZoom}>
        {selectMode && (
          <span className={`cc-check${isSelected ? " cc-check--on" : ""}`} aria-hidden="true">
            {isSelected ? "✓" : ""}
          </span>
        )}
        <img
          src={thumbUrl || photoSrc(item.url)}
          alt={item.filename}
          loading="lazy"
          decoding="async"
          onLoad={() => setImgLoaded(true)}
          onError={fallbackToIcon}
        />
        {!ownedByMe && ownerInitial && (
          <div className="circle-owner-badge">{ownerInitial}</div>
        )}
        {inLaundry && (
          <span className="closet-laundry-badge" title="In the laundry">In the wash</span>
        )}
        {wearCount > 0 && (
          <span className="closet-wear-badge"
                title={lastWorn
                  ? `Worn ${wearCount} time${wearCount === 1 ? "" : "s"}, last on ${new Date(lastWorn).toLocaleDateString()}`
                  : `Worn ${wearCount} time${wearCount === 1 ? "" : "s"}`}>
            {wearCount}x
          </span>
        )}

        {/* Logging a wear is the thing done most, so it is the one button that
            is always there. The rest sit behind the menu rather than crowding
            the card -- four buttons used to cover the item's own name. */}
        {ownedByMe !== false && !selectMode && (
          <div className="cc-actions" onClick={(e) => e.stopPropagation()}>
            <button className="cc-act cc-act--wear" onClick={markWorn} disabled={wearBusy}
                    title="I wore this today" aria-label="I wore this today">
              <span className="cc-act-glyph">✓</span>
              <span className="cc-act-text">Wore it</span>
            </button>
            <div className="cc-menu-wrap">
              <button className="cc-act cc-act--more" onClick={() => setMenuOpen((v) => !v)}
                      title="More" aria-label="More actions" aria-expanded={menuOpen}>⋯</button>
              {menuOpen && (
                <div className="cc-menu" onMouseLeave={() => setMenuOpen(false)}>
                  <button onClick={(e) => { setMenuOpen(false); toggleLaundry(e); }}
                          disabled={wearBusy}>
                    {inLaundry ? "Take out of the wash" : "Put in the wash"}
                  </button>
                  <button onClick={() => { setMenuOpen(false); onEdit(); }}>Edit details</button>
                  <button className="cc-menu-danger"
                          onClick={() => {
                            setMenuOpen(false);
                            if (window.confirm(`Delete "${item.matched_title || item.caption || item.filename}" from your closet? This cannot be undone.`)) onDelete();
                          }}>
                    Delete
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="closet-card-body">
        <p className="closet-card-type">
          {item.matched_title || item.caption || item.type || "—"}
        </p>
        <p className="closet-card-brand">
          {item.brand || "\u2014"}
        </p>
        <div className="closet-card-tags">
          {item.subcategory
            ? <span className="closet-tag-chip closet-tag-chip--subcat">{item.subcategory.replace(/_/g, " ")}</span>
            : item.category && <span className="closet-tag-chip">{item.category}</span>
          }
          {item.size && <span className="closet-tag-chip">Size {item.size}</span>}
          {item.color && <span className="closet-tag-chip">{item.color}</span>}
        </div>

      </div>
    </motion.div>
  );
}

export default Closet;
