import React, { useEffect, useRef, useState } from "react";
import axios from "axios";
import Layout from "./Layout";
import "./Friends.css";

import { API_BASE as API, iconSrc, photoSrc } from "../config";

export default function Friends() {
  const [tab, setTab] = useState("friends");
  const [friends, setFriends] = useState([]);
  const [pendingRequests, setPendingRequests] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [pendingSent, setPendingSent] = useState([]);
  const [pendingReceived, setPendingReceived] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [myStatus, setMyStatus] = useState("");
  const [editingStatus, setEditingStatus] = useState(false);
  const [statusDraft, setStatusDraft] = useState("");

  // Closet modal state
  const [viewingCloset, setViewingCloset] = useState(null); // friend object
  const [friendCloset, setFriendCloset] = useState([]);
  const [closetLoading, setClosetLoading] = useState(false);

  const debounceRef = useRef(null);
  const token = localStorage.getItem("token");

  const authH = () => ({ Authorization: `Bearer ${token}` });

  useEffect(() => {
    fetchFriends();
    fetchPendingRequests();
  }, []);

  const fetchFriends = async () => {
    try {
      const res = await axios.get(`${API}/get_friends`, { headers: authH() });
      setFriends(res.data);
    } catch (e) { console.error(e); }
  };

  const fetchPendingRequests = async () => {
    try {
      const res = await axios.get(`${API}/pending_friend_requests`, { headers: authH() });
      setPendingRequests(res.data);
    } catch (e) { console.error(e); }
  };

  const runSearch = async (q) => {
    if (!q.trim()) { setSearchResults([]); return; }
    try {
      const res = await axios.get(`${API}/search_users`, { headers: authH(), params: { q } });
      setSearchResults(res.data.results || []);
      setPendingSent(res.data.pending_sent || []);
      setPendingReceived(res.data.pending_received || []);
    } catch (e) { console.error(e); }
  };

  const onSearchChange = (val) => {
    setSearchQuery(val);
    clearTimeout(debounceRef.current);
    if (val.trim().length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await axios.get(`${API}/search_users`, { headers: authH(), params: { q: val } });
        const results = res.data.results || [];
        setSuggestions(results.slice(0, 6));
        setShowSuggestions(results.length > 0);
        setSearchResults(results);
        setPendingSent(res.data.pending_sent || []);
        setPendingReceived(res.data.pending_received || []);
      } catch (e) { console.error(e); }
    }, 280);
  };

  const pickSuggestion = (user) => {
    setSearchQuery(user.email);
    setSuggestions([]);
    setShowSuggestions(false);
    setSearchResults([user]);
  };

  const sendRequest = async (target_id) => {
    try {
      await axios.post(`${API}/send_friend_request`, { target_id }, { headers: { ...authH(), "Content-Type": "application/json" } });
      setPendingSent((prev) => [...prev, target_id]);
    } catch (e) {
      alert(e.response?.data?.message || "Failed to send request.");
    }
  };

  const respondToRequest = async (request_id, action) => {
    try {
      await axios.post(
        `${API}/respond_to_friend_request`,
        { request_id, action },
        { headers: { ...authH(), "Content-Type": "application/json" } }
      );
      setPendingRequests((prev) => prev.filter((r) => r.id !== request_id));
      if (action === "accept") fetchFriends();
    } catch (e) { console.error(e); }
  };

  const removeFriend = async (friend_id) => {
    if (!window.confirm("Remove this friend?")) return;
    try {
      await axios.delete(`${API}/remove_friend`, { headers: authH(), params: { friend_id } });
      setFriends((prev) => prev.filter((f) => f.id !== friend_id));
    } catch (e) { console.error(e); }
  };

  const openCloset = async (friend) => {
    setViewingCloset(friend);
    setFriendCloset([]);
    setClosetLoading(true);
    try {
      const res = await axios.get(`${API}/friends/${friend.id}/closet`, { headers: authH() });
      setFriendCloset(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setClosetLoading(false);
    }
  };

  const saveStatus = async () => {
    try {
      await axios.post(
        `${API}/update_status`,
        { status_caption: statusDraft },
        { headers: { ...authH(), "Content-Type": "application/json" } }
      );
      setMyStatus(statusDraft);
      setEditingStatus(false);
    } catch (e) { console.error(e); }
  };

  const avatar = (email) => (email || "?")[0].toUpperCase();

  return (
    <Layout>
      <div className="friends-page">
        {/* ── Page header ───────────────────────────────────────────────── */}
        <div className="friends-page-header">
          <h1 className="page-heading">Friends</h1>
          {pendingRequests.length > 0 && (
            <button className="requests-badge" onClick={() => setTab("requests")}>
              {pendingRequests.length} pending
            </button>
          )}
        </div>

        {/* ── My status strip ──────────────────────────────────────────── */}
        <div className="my-status-strip section-card">
          <div className="my-status-avatar">Me</div>
          {editingStatus ? (
            <div className="my-status-edit">
              <input
                className="field-input"
                value={statusDraft}
                onChange={(e) => setStatusDraft(e.target.value)}
                placeholder="What are you wearing today?"
                maxLength={160}
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && saveStatus()}
              />
              <button className="btn-primary" onClick={saveStatus}>Save</button>
              <button className="btn-secondary" onClick={() => setEditingStatus(false)}>Cancel</button>
            </div>
          ) : (
            <div className="my-status-display" onClick={() => { setStatusDraft(myStatus); setEditingStatus(true); }}>
              <span className="my-status-text">{myStatus || "Set a status…"}</span>
              <span className="my-status-edit-hint">✏️</span>
            </div>
          )}
        </div>

        {/* ── Tabs ─────────────────────────────────────────────────────── */}
        <div className="friends-tabs">
          <button className={`friends-tab${tab === "friends" ? " active" : ""}`} onClick={() => setTab("friends")}>
            Friends <span className="tab-count">{friends.length}</span>
          </button>
          <button className={`friends-tab${tab === "add" ? " active" : ""}`} onClick={() => setTab("add")}>
            Add Friends
          </button>
          <button className={`friends-tab${tab === "requests" ? " active" : ""}`} onClick={() => setTab("requests")}>
            Requests
            {pendingRequests.length > 0 && <span className="tab-badge">{pendingRequests.length}</span>}
          </button>
        </div>

        {/* ── Friends tab ──────────────────────────────────────────────── */}
        {tab === "friends" && (
          <div className="friends-grid">
            {friends.length === 0 && (
              <div className="friends-empty">
                <p>No friends yet.</p>
                <button className="btn-primary" onClick={() => setTab("add")}>Find friends</button>
              </div>
            )}
            {friends.map((f) => (
              <FriendCard
                key={f.id}
                friend={f}
                avatar={avatar}
                onRemove={() => removeFriend(f.id)}
                onViewCloset={() => openCloset(f)}
              />
            ))}
          </div>
        )}

        {/* ── Add Friends tab ───────────────────────────────────────────── */}
        {tab === "add" && (
          <div>
            <div className="add-friends-search">
              <div style={{ flex: 1, position: "relative" }}>
                <input
                  className="field-input"
                  placeholder="Search by email…"
                  value={searchQuery}
                  onChange={(e) => onSearchChange(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && runSearch(searchQuery)}
                  onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                  onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                />
                {showSuggestions && (
                  <div className="search-dropdown">
                    {suggestions.map((u) => {
                      const sent = pendingSent.includes(u.id);
                      const received = pendingReceived.includes(u.id);
                      return (
                        <div key={u.id} className="search-dropdown-item" onMouseDown={() => pickSuggestion(u)}>
                          <span className="sdi-avatar">{avatar(u.email)}</span>
                          <span className="sdi-email">{u.email}</span>
                          {(sent || received) && (
                            <span style={{ fontSize: "0.72rem", color: "#7070a0", marginLeft: "auto" }}>Pending</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
              <button className="btn-primary" onClick={() => runSearch(searchQuery)}>Search</button>
            </div>

            {searchResults.length > 0 && (
              <div className="search-results-list">
                {searchResults.map((u) => {
                  const sent = pendingSent.includes(u.id);
                  const received = pendingReceived.includes(u.id);
                  return (
                    <div key={u.id} className="search-result-row">
                      <div className="sr-avatar">{avatar(u.email)}</div>
                      <span className="sr-email">{u.email}</span>
                      {sent || received ? (
                        <span className="sr-pending">Pending</span>
                      ) : (
                        <button
                          className="btn-primary"
                          style={{ fontSize: "0.8rem", padding: "6px 14px" }}
                          onClick={() => sendRequest(u.id)}
                        >
                          + Add
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {searchQuery && !showSuggestions && searchResults.length === 0 && (
              <p className="friends-empty-text">No users found for "{searchQuery}".</p>
            )}
          </div>
        )}

        {/* ── Requests tab ──────────────────────────────────────────────── */}
        {tab === "requests" && (
          <div>
            {pendingRequests.length === 0 && (
              <p className="friends-empty-text">No pending friend requests.</p>
            )}
            {pendingRequests.map((req) => (
              <div key={req.id} className="request-row">
                <div className="sr-avatar">{avatar(req.from_email)}</div>
                <div className="request-info">
                  <span className="sr-email">{req.from_email}</span>
                  <span className="request-sub">wants to be friends</span>
                </div>
                <div className="request-actions">
                  <button className="btn-accept" onClick={() => respondToRequest(req.id, "accept")}>Accept</button>
                  <button className="btn-decline" onClick={() => respondToRequest(req.id, "decline")}>Decline</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Friend closet modal ───────────────────────────────────────────── */}
      {viewingCloset && (
        <div className="modal-overlay" onClick={() => setViewingCloset(null)}>
          <div className="modal-box friend-closet-modal" onClick={(e) => e.stopPropagation()}>
            <div className="shared-closet-header">
              <div className="friend-avatar" style={{ width: 44, height: 44, fontSize: "1.1rem" }}>
                {avatar(viewingCloset.email)}
              </div>
              <div>
                <p style={{ margin: 0, fontWeight: 600, color: "#d0d0e8" }}>{viewingCloset.email}</p>
                <p style={{ margin: 0, fontSize: "0.75rem", color: "#666" }}>
                  {friendCloset.length} item{friendCloset.length !== 1 ? "s" : ""}
                </p>
              </div>
              <button className="modal-close" onClick={() => setViewingCloset(null)}>✕</button>
            </div>

            {closetLoading && <p style={{ color: "#555", textAlign: "center", padding: "32px 0" }}>Loading closet…</p>}

            {!closetLoading && friendCloset.length === 0 && (
              <p style={{ color: "#555", textAlign: "center", padding: "32px 0" }}>This closet is empty.</p>
            )}

            {!closetLoading && friendCloset.length > 0 && (
              <div className="shared-closet-grid">
                {friendCloset.map((item) => {
                  const imgSrc = item.icon_path ? iconSrc(item.icon_path) : photoSrc(item.url);
                  return (
                    <div key={item.id} className="shared-closet-card">
                      <img src={imgSrc} alt={item.brand || item.filename} />
                      <div className="shared-closet-card-label">
                        <span className="scc-brand">{item.brand || item.filename}</span>
                        {item.category && <span className="scc-chip">{item.category}</span>}
                        {item.color && <span className="scc-chip">{item.color}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </Layout>
  );
}

function FriendCard({ friend, avatar, onRemove, onViewCloset }) {
  const isOnline = friend.last_seen === "🟢 Online";

  return (
    <div className="friend-card">
      <div className="friend-card-top">
        <div className="friend-avatar-wrap">
          <div className="friend-avatar">{avatar(friend.email)}</div>
          <span className={`online-dot${isOnline ? " online" : ""}`} />
        </div>
        <div className="friend-info">
          <span className="friend-email">{friend.email}</span>
          {friend.status_caption && <span className="friend-status">{friend.status_caption}</span>}
          <span className="friend-seen">{friend.last_seen}</span>
        </div>
      </div>
      <div className="friend-card-actions">
        <button
          className="btn-secondary"
          style={{ fontSize: "0.78rem", padding: "5px 12px" }}
          onClick={onViewCloset}
        >
          View Closet
        </button>
        <button className="btn-danger" onClick={onRemove}>Remove</button>
      </div>
    </div>
  );
}
