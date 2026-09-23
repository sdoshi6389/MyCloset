import { motion, useReducedMotion } from "framer-motion";
import "./AmbientField.css";

/* The drifting colour field from the landing page, reusable so the app does not
 * drop to flat panels the moment you sign in. `variant="app"` dims it well below
 * the marketing version, since content has to stay readable on top of it. */
export default function AmbientField({ variant = "hero" }) {
  const reduce = useReducedMotion();
  return (
    <div className={`af-root af-root--${variant}`} aria-hidden>
      {["a", "b", "c"].map((k, i) => (
        <motion.span
          key={k}
          className={`af-orb af-orb--${k}`}
          animate={reduce ? {} : {
            x: [0, 40 * (i + 1), -30 * (i + 1), 0],
            y: [0, -50 * (i + 1), 30 * (i + 1), 0],
            scale: [1, 1.15, 0.95, 1],
          }}
          transition={{ duration: 22 + i * 7, repeat: Infinity, ease: "easeInOut" }}
        />
      ))}
      <div className="af-grid" />
    </div>
  );
}
