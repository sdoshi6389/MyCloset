import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import axios from "axios";
import Layout from "./Layout";
import { useCircle } from "../context/CircleContext";
import "./Closet.css";

import { API_BASE as API } from "../config";

const DEFAULT_CATEGORIES = ["Tops", "Bottoms", "Outerwear", "Innerwear", "Accessories", "Shoes"];

function Closet() {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState(DEFAULT_CATEGORIES);
  const [files, setFiles] = useState([]);
  const [isCameraOn, setIsCameraOn] = useState(false);

  // Metadata modal state
  const [modalQueue, setModalQueue] = useState([]);
  const [activeItem, setActiveItem] = useState(null);
  const [nameInput, setNameInput] = useState("");
  const [gptBrandHint, setGptBrandHint] = useState(null);
  const [brandInput, setBrandInput] = useState("");
  const [sizeInput, setSizeInput] = useState("");
  const [categoryInput, setCategoryInput] = useState("");
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

  const authHeaders = () => ({ Authorization: `Bearer ${token}` });

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
    if (!window.confirm("Regenerate icons for all items missing icons using GPT? This may take several minutes.")) return;
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

    await Promise.all(
      toUpload.map(async (file, idx) => {
        const formData = new FormData();
        formData.append("files", file);
        try {
          const res = await axios.post(`${API}/upload_closet_images`, formData, {
            headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
          });
          const returned = res.data.items || [];
          if (returned.length) {
            slots[idx] = returned[0];
            // Card appears immediately as each upload finishes
            setItems((prev) =>
              prev.some((p) => p.id === returned[0].id) ? prev : [...prev, returned[0]]
            );
          }
        } catch (err) {
          console.error(`Upload failed for ${file.name}:`, err);
        } finally {
          setUploadProgress((prev) => prev ? { ...prev, done: prev.done + 1 } : null);
        }
      })
    );

    const uploaded = slots.filter(Boolean);
    setFiles([]);
    setUploading(false);
    setUploadProgress(null);

    if (!uploaded.length) return;

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

  // ── Modal queue ──────────────────────────────────────────────────────────────
  const stopBrandPoll = () => {
    if (brandPollRef.current) {
      clearInterval(brandPollRef.current);
      brandPollRef.current = null;
    }
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
        await axios.post(`${API}/upload_closet_images`, fd, {
          headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
        });
        fetchItems();
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

  const grouped = {};
  (activeCategory === "All" ? [...categories, "Uncategorized"] : [activeCategory]).forEach((cat) => {
    let group = items.filter((it) =>
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
        {["All", ...categories].map((cat) => (
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
            {catItems.map((item) => {
              const ownedByMe = !item.owner_email || item.owner_email === currentEmail;
              return (
                <ClosetItemCard
                  key={item.id}
                  item={item}
                  ownedByMe={ownedByMe}
                  ownerInitial={item.owner_initial}
                  onZoom={() => setZoomedItem(item)}
                  onEdit={ownedByMe ? () => {
                    setActiveItem(item);
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

      {/* ── Metadata modal ──────────────────────────────────────────────────── */}
      {activeItem && !faissMatches.length && (
        <div className="modal-overlay" onClick={() => setActiveItem(null)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h3>
              {activeItem.filename}
              {modalQueue.length > 0 && (
                <span style={{ fontSize: "0.75rem", color: "#8080a8", marginLeft: 10 }}>
                  {modalQueue.length} more after this
                </span>
              )}
            </h3>

            {activeItem.icon_path && (
              <img
                src={`${API}/icons/${activeItem.icon_path.split(/[/\\]/).pop()}`}
                alt="icon"
                className="modal-item-icon"
              />
            )}

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
              <button className="btn-secondary" onClick={() => setActiveItem(null)} style={{ marginLeft: "auto" }}>Cancel</button>
            </div>
            <p className="modal-action-hint">
              <strong>Save</strong> stores brand/size/category.
              {activeItem.has_embedding
                ? <>&nbsp;<strong>Find Match</strong> searches the product database for a similar item.</>
                : <>&nbsp;Product matching becomes available once the AI finishes processing this item.</>
              }
            </p>
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
            src={`${API}${zoomedItem.url}?t=${Date.now()}`}
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

function ClosetItemCard({ item, ownedByMe, ownerInitial, onZoom, onEdit, onDelete }) {
  const [hovered, setHovered] = useState(false);
  const [hoverPos, setHoverPos] = useState(null);
  const cardRef = useRef(null);

  const fname = iconFilename(item.icon_path);
  const iconUrl = fname ? `${API}/icons/${encodeURIComponent(fname)}` : null;

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
    <div
      ref={cardRef}
      className="closet-card"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => { setHovered(false); setHoverPos(null); }}
    >
      {hovered && hasGptData && hoverPos && (
        <ItemHoverCard item={item} iconUrl={iconUrl} pos={hoverPos} />
      )}

      <div className="closet-card-image" onClick={onZoom}>
        <img src={`${API}${item.url}`} alt={item.filename} />
        {iconUrl && <img src={iconUrl} alt="icon" className="closet-card-icon-badge" />}
        {!ownedByMe && ownerInitial && (
          <div className="circle-owner-badge">{ownerInitial}</div>
        )}
      </div>

      <div className="closet-card-body">
        <p className="closet-card-type">
          {item.matched_title || item.caption || item.type || "—"}
        </p>
        <p className="closet-card-brand">
          {item.brand || "Unknown"}
        </p>
        <div className="closet-card-tags">
          {item.subcategory
            ? <span className="closet-tag-chip closet-tag-chip--subcat">{item.subcategory.replace(/_/g, " ")}</span>
            : item.category && <span className="closet-tag-chip">{item.category}</span>
          }
          {item.size && <span className="closet-tag-chip">Size {item.size}</span>}
          {item.color && <span className="closet-tag-chip">{item.color}</span>}
        </div>
        {ownedByMe !== false && (
          <div className="closet-card-actions">
            <button className="btn-secondary" style={{ fontSize: "0.78rem", padding: "5px 10px" }} onClick={onEdit}>
              Edit
            </button>
            <button className="btn-danger" onClick={onDelete}>Delete</button>
          </div>
        )}
      </div>
    </div>
  );
}

function ItemHoverCard({ item, iconUrl, pos }) {
  const tags = [
    { label: "Type",     value: item.subcategory ? item.subcategory.replace(/_/g, " ") : item.type },
    { label: "Layer",    value: item.layering_role ? item.layering_role.replace(/_/g, " ") : null },
    { label: "Color",    value: item.color },
    { label: "Style",    value: item.style },
    { label: "Season",   value: item.season },
    { label: "Fabric",   value: item.fabric },
    { label: "Vibe",     value: item.vibe },
    { label: "Gender",   value: item.gender },
  ].filter((t) => t.value);

  const keywords = Array.isArray(item.keywords)
    ? item.keywords
    : typeof item.keywords === "string" && item.keywords
    ? item.keywords.replace(/[\[\]'"]/g, "").split(",").map((k) => k.trim()).filter(Boolean)
    : [];

  return createPortal(
    <div className="item-hover-card" style={{ left: pos.x, top: pos.y }}>
      {(iconUrl || item.caption) && (
        <div className="ihc-top">
          {iconUrl && <img src={iconUrl} alt="icon" className="ihc-icon" />}
          {item.caption && <p className="ihc-caption">{item.caption}</p>}
        </div>
      )}

      {tags.length > 0 && (
        <div className="ihc-tag-grid">
          {tags.map(({ label, value }) => (
            <div key={label} className="ihc-tag-row">
              <span className="ihc-tag-label">{label}</span>
              <span className="ihc-tag-value">{value}</span>
            </div>
          ))}
        </div>
      )}

      {keywords.length > 0 && (
        <div className="ihc-keywords">
          {keywords.slice(0, 8).map((k, i) => (
            <span key={i} className="ihc-keyword-chip">{k}</span>
          ))}
        </div>
      )}
    </div>,
    document.body
  );
}

export default Closet;
