import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("Uncaught error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", minHeight: "100vh",
          background: "#0f0f1a", color: "#e0e0f0", fontFamily: "sans-serif",
          gap: 16, padding: 32,
        }}>
          <h2 style={{ color: "#ff6b6b", margin: 0 }}>Something went wrong</h2>
          <p style={{ color: "#8080a8", margin: 0, textAlign: "center", maxWidth: 420 }}>
            An unexpected error occurred. Try refreshing the page.
          </p>
          <details style={{ color: "#555570", fontSize: "0.8rem", maxWidth: 540, wordBreak: "break-word" }}>
            <summary style={{ cursor: "pointer" }}>Error details</summary>
            <pre style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
              {this.state.error?.toString()}
            </pre>
          </details>
          <button
            onClick={() => window.location.reload()}
            style={{
              background: "#5b5bff", color: "#fff", border: "none",
              borderRadius: 8, padding: "10px 24px", cursor: "pointer", fontSize: "0.9rem",
            }}
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
