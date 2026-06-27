import React, { useRef, useState } from "react";
import axios from "axios";
import Layout from "./Layout";
import { useCircle } from "../context/CircleContext";
import "./Circles.css";

const API = "http://localhost:5000";

function iconFilename(iconPath) {
  if (!iconPath) return null;
  return iconPath.split(/[/\\]/).pop();
}

export default function Circles() {
  const { circles, refreshCircles } = useCircle();
  const [selectedCircle, setSelectedCircle] = useState(null);
  const [members, setMembers] = useState([]);
  const [newCircleName, setNewCircleName] = useState("");
  const [newCircleDesc, setNewCircleDesc] = useState("");
  const [addEmail, setAddEmail] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [sharedCloset, setSharedCloset] = useState(null); // { member, items }
  const debounceRef = useRef(null);
  const token = localStorage.getItem("token");

  const authH = () => ({ Authorization: `Bearer ${token}` });

  const selectCircle = async (circle) => {
    setSelectedCircle(circle);
    setSharedCloset(null);
    try {
      const res = await axios.get(`${API}/circles/${circle.id}/members`, { headers: authH() });
      setMembers(res.data);
    } catch (e) { console.error(e); }
  };

  const createCircle = async () => {
    const name = newCircleName.trim();
    if (!name) return;
    try {
      await axios.post(
        `${API}/circles`,
        { name, description: newCircleDesc.trim() || undefined },
        { headers: { ...authH(), "Content-Type": "application/json" } }
      );
      setNewCircleName(""); setNewCircleDesc(""); setShowCreateForm(false);
      refreshCircles();
    } catch (e) { console.error(e); alert("Failed to create circle."); }
  };

  const deleteCircle = async (id) => {
    if (!window.confirm("Delete this circle?")) return;
    try {
      await axios.delete(`${API}/circles/${id}`, { headers: authH() });
      if (selectedCircle?.id === id) { setSelectedCircle(null); setMembers([]); }
      refreshCircles();
    } catch (e) { console.error(e); }
  };

  const addMember = async (emailOverride) => {
    const email = (emailOverride ?? addEmail).trim();
    if (!email || !selectedCircle) return;
    try {
      await axios.post(
        `${API}/circles/${selectedCircle.id}/members`,
        { email },
        { headers: { ...authH(), "Content-Type": "application/json" } }
      );
      setAddEmail(""); setSuggestions([]); setShowSuggestions(false);
      selectCircle(selectedCircle);
    } catch (e) {
      alert(e.response?.data?.message || "Failed to add member.");
    }
  };

  const removeMember = async (userId) => {
    if (!selectedCircle) return;
    try {
      await axios.delete(`${API}/circles/${selectedCircle.id}/members/${userId}`, { headers: authH() });
      selectCircle(selectedCircle);
    } catch (e) { console.error(e); }
  };

  const viewMemberCloset = async (member) => {
    try {
      const res = await axios.get(
        `${API}/circles/${selectedCircle.id}/member/${member.id}/closet`,
        { headers: authH() }
      );
      setSharedCloset({ member, items: res.data });
    } catch (e) {
      alert(e.response?.data?.message || "Could not load closet.");
    }
  };

  const onAddEmailChange = (val) => {
    setAddEmail(val);
    clearTimeout(debounceRef.current);
    if (val.trim().length < 2) { setSuggestions([]); setShowSuggestions(false); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await axios.get(`${API}/search_users`, { headers: authH(), params: { q: val } });
        const memberIds = new Set(members.map((m) => m.id));
        const filtered = (res.data.results || []).filter((u) => !memberIds.has(u.id));
        setSuggestions(filtered.slice(0, 6));
        setShowSuggestions(filtered.length > 0);
      } catch (e) { console.error(e); }
    }, 280);
  };

  const pickSuggestion = (user) => {
    setAddEmail(user.email); setSuggestions([]); setShowSuggestions(false);
    addMember(user.email);
  };

  return (
    <Layout>
      <div className="circles-header">
        <h1 className="page-heading">Circles</h1>
        <button className="btn-primary" onClick={() => setShowCreateForm(true)}>+ New Circle</button>
      </div>

      {/* ── Create circle modal ────────────────────────────────────────────── */}
      {showCreateForm && (
        <div className="modal-overlay" onClick={() => setShowCreateForm(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h3>Create a Circle</h3>
            <div className="field-group">
              <label className="field-label">Circle Name</label>
              <input className="field-input" value={newCircleName} onChange={(e) => setNewCircleName(e.target.value)} placeholder="e.g. Campus Friends" />
            </div>
            <div className="field-group">
              <label className="field-label">Description (optional)</label>
              <input className="field-input" value={newCircleDesc} onChange={(e) => setNewCircleDesc(e.target.value)} placeholder="What is this circle about?" />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn-primary" onClick={createCircle}>Create</button>
              <button className="btn-secondary" onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Shared closet modal ────────────────────────────────────────────── */}
      {sharedCloset && (
        <div className="modal-overlay" onClick={() => setSharedCloset(null)}>
          <div className="modal-box shared-closet-modal" onClick={(e) => e.stopPropagation()}>
            <div className="shared-closet-header">
              <div className="member-avatar">{sharedCloset.member.email[0].toUpperCase()}</div>
              <div>
                <h3 style={{ margin: 0 }}>{sharedCloset.member.email}'s Closet</h3>
                <p style={{ margin: 0, fontSize: "0.78rem", color: "#8080a8" }}>
                  {sharedCloset.items.length} item{sharedCloset.items.length !== 1 ? "s" : ""}
                </p>
              </div>
              <button className="btn-secondary" style={{ marginLeft: "auto" }} onClick={() => setSharedCloset(null)}>Close</button>
            </div>

            {sharedCloset.items.length === 0 ? (
              <p style={{ color: "#555", textAlign: "center", padding: 24 }}>No items in their closet yet.</p>
            ) : (
              <div className="shared-closet-grid">
                {sharedCloset.items.map((item) => {
                  const fname = iconFilename(item.icon_path);
                  const imgSrc = fname
                    ? `${API}/icons/${encodeURIComponent(fname)}`
                    : `${API}${item.url}`;
                  return (
                    <div key={item.id} className="shared-closet-card">
                      <img src={imgSrc} alt={item.brand || item.filename} />
                      <div className="shared-closet-card-label">
                        <span className="scc-brand">{item.brand || "Unknown"}</span>
                        {item.color && <span className="scc-chip">{item.color}</span>}
                        {item.type && <span className="scc-chip">{item.type}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="circles-layout">
        {/* ── Left: circles list ──────────────────────────────────────────── */}
        <aside className="circles-list-panel section-card">
          <h3 className="circles-panel-heading">Your Circles</h3>
          {circles.length === 0 && (
            <p style={{ color: "#555", fontSize: "0.875rem" }}>No circles yet. Create one!</p>
          )}
          {circles.map((c) => (
            <div
              key={c.id}
              className={`circle-list-item${selectedCircle?.id === c.id ? " active" : ""}`}
              onClick={() => selectCircle(c)}
            >
              <div className="circle-list-icon">👥</div>
              <div className="circle-list-info">
                <span className="circle-list-name">{c.name}</span>
                <span className="circle-list-meta">{c.member_count} member{c.member_count !== 1 ? "s" : ""}</span>
              </div>
              <button
                className="btn-danger"
                style={{ marginLeft: "auto", fontSize: "0.72rem", padding: "4px 8px" }}
                onClick={(e) => { e.stopPropagation(); deleteCircle(c.id); }}
              >✕</button>
            </div>
          ))}
        </aside>

        {/* ── Right: circle detail ─────────────────────────────────────────── */}
        <div className="circles-detail">
          {!selectedCircle ? (
            <div className="circles-empty section-card">
              <p>Select a circle to view its members.</p>
            </div>
          ) : (
            <div className="section-card">
              <h3 className="circles-panel-heading">{selectedCircle.name}</h3>
              {selectedCircle.description && (
                <p style={{ color: "#8080a8", fontSize: "0.875rem", marginTop: -8, marginBottom: 16 }}>
                  {selectedCircle.description}
                </p>
              )}

              {/* Add member with autocomplete */}
              <div className="add-member-row">
                <div style={{ flex: 1, position: "relative" }}>
                  <input
                    className="field-input"
                    placeholder="Add member by email…"
                    value={addEmail}
                    onChange={(e) => onAddEmailChange(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addMember()}
                    onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                    onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                  />
                  {showSuggestions && (
                    <div className="search-dropdown">
                      {suggestions.map((u) => (
                        <div key={u.id} className="search-dropdown-item" onMouseDown={() => pickSuggestion(u)}>
                          <span className="sdi-avatar">{u.email[0].toUpperCase()}</span>
                          <span className="sdi-email">{u.email}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <button className="btn-primary" onClick={() => addMember()}>Add</button>
              </div>

              {/* Members list */}
              <div className="members-list">
                {members.map((m) => (
                  <div key={m.id} className="member-row">
                    <div className="member-avatar">{m.email[0].toUpperCase()}</div>
                    <div className="member-info">
                      <span className="member-email">{m.email}</span>
                      <span className="member-role">{m.role}</span>
                    </div>
                    <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
                      {m.role !== "owner" && (
                        <button
                          className="btn-secondary"
                          style={{ fontSize: "0.72rem", padding: "4px 10px" }}
                          onClick={() => viewMemberCloset(m)}
                        >
                          View Closet
                        </button>
                      )}
                      {m.role !== "owner" && (
                        <button
                          className="btn-danger"
                          style={{ fontSize: "0.72rem", padding: "4px 8px" }}
                          onClick={() => removeMember(m.id)}
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
