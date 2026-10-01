import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "./apiClient"; // registers global axios refresh interceptor

/* So "is this a bug or an old build?" is one glance at the console. */
console.info(`%c[MyCloset] build ${__BUILD_ID__}`, "color:#a78bfa");

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
