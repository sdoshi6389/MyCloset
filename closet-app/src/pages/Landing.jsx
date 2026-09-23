import { Fragment, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { motion, useScroll, useTransform, useReducedMotion } from "framer-motion";
import "./Landing.css";

const FEATURES = [
  {
    key: "closet",
    tag: "Your wardrobe",
    title: "Every piece you own, in one place",
    body: "Photograph a garment and it is cut out, tagged and filed by category, colour and brand. No forms to fill in.",
    grad: "var(--grad-violet)",
  },
  {
    key: "builder",
    tag: "Outfit builder",
    title: "Put looks together before you get dressed",
    body: "Drag pieces onto the canvas, layer them, flip to underlayers, and save the outfits that work.",
    grad: "var(--grad-cyan)",
  },
  {
    key: "recs",
    tag: "Suggestions",
    title: "Find what is missing from a look",
    body: "Ask for the slot you have not filled and get pieces from your own closet, or from the catalog when you want to buy.",
    grad: "var(--grad-amber)",
  },
  {
    key: "circles",
    tag: "Circles",
    title: "Share a closet with the people you dress with",
    body: "Build shared circles, see what friends are wearing, and borrow from each other's wardrobes.",
    grad: "var(--grad-rose)",
  },
];

const EASE = [0.22, 1, 0.36, 1];

export default function Landing() {
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const heroRef = useRef(null);
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ["start start", "end start"] });
  const heroY = useTransform(scrollYProgress, [0, 1], [0, reduce ? 0 : 120]);
  const heroFade = useTransform(scrollYProgress, [0, 0.8], [1, 0]);

  // Someone already signed in has no use for the pitch.
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    try {
      const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      if (payload.exp * 1000 > Date.now()) navigate("/closet", { replace: true });
    } catch {
      localStorage.removeItem("token");
    }
  }, [navigate]);

  const words = "Your whole wardrobe, finally organised.".split(" ");

  return (
    <div className="lp-root">
      {/* Ambient colour field */}
      <div className="lp-field" aria-hidden>
        {["a", "b", "c"].map((k, i) => (
          <motion.span
            key={k}
            className={`lp-orb lp-orb--${k}`}
            animate={reduce ? {} : {
              x: [0, 40 * (i + 1), -30 * (i + 1), 0],
              y: [0, -50 * (i + 1), 30 * (i + 1), 0],
              scale: [1, 1.15, 0.95, 1],
            }}
            transition={{ duration: 22 + i * 7, repeat: Infinity, ease: "easeInOut" }}
          />
        ))}
        <div className="lp-grid" />
      </div>

      <header className="lp-nav">
        <span className="lp-wordmark">MyCloset</span>
        <button className="lp-nav-cta" onClick={() => navigate("/login")}>Sign in</button>
      </header>

      <motion.section ref={heroRef} className="lp-hero" style={{ y: heroY, opacity: heroFade }}>
        <motion.p
          className="lp-eyebrow"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE }}
        >
          A closet that knows what is in it
        </motion.p>

        <h1 className="lp-headline">
          {/* The space lives outside the inline-block span: inside it the layout
              collapses it, and moving the gap into CSS would leave the heading
              reading as one run-on word to screen readers and to copy-paste. */}
          {words.map((w, i) => (
            <Fragment key={i}>
              <motion.span
                className="lp-word"
                initial={{ opacity: 0, y: 28, filter: "blur(8px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={{ duration: 0.75, ease: EASE, delay: 0.15 + i * 0.07 }}
              >
                {w}
              </motion.span>{" "}
            </Fragment>
          ))}
        </h1>

        <motion.p
          className="lp-sub"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE, delay: 0.55 }}
        >
          Photograph what you own, build outfits on a canvas, and get suggestions
          for the pieces a look is missing.
        </motion.p>

        <motion.div
          className="lp-cta-row"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE, delay: 0.7 }}
        >
          <motion.button
            className="lp-cta"
            onClick={() => navigate("/login")}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.97 }}
          >
            Get started
          </motion.button>
          <motion.button
            className="lp-cta lp-cta--ghost"
            onClick={() => document.getElementById("lp-features")?.scrollIntoView({ behavior: "smooth" })}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.97 }}
          >
            See how it works
          </motion.button>
        </motion.div>

        <motion.div
          className="lp-scroll-hint"
          aria-hidden
          animate={reduce ? {} : { y: [0, 8, 0], opacity: [0.45, 1, 0.45] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
        />
      </motion.section>

      <section className="lp-features" id="lp-features">
        {FEATURES.map((f, i) => (
          <motion.article
            key={f.key}
            className="lp-feature"
            initial={{ opacity: 0, y: 44 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.35 }}
            transition={{ duration: 0.7, ease: EASE }}
          >
            <motion.div
              className="lp-feature-swatch"
              style={{ background: f.grad }}
              initial={{ scale: 0.86, opacity: 0 }}
              whileInView={{ scale: 1, opacity: 1 }}
              viewport={{ once: true, amount: 0.35 }}
              transition={{ duration: 0.8, ease: EASE, delay: 0.08 }}
            />
            <div className="lp-feature-text">
              <span className="lp-feature-tag">{f.tag}</span>
              <h2 className="lp-feature-title">{f.title}</h2>
              <p className="lp-feature-body">{f.body}</p>
            </div>
            <span className="lp-feature-index">{String(i + 1).padStart(2, "0")}</span>
          </motion.article>
        ))}
      </section>

      <motion.section
        className="lp-close"
        initial={{ opacity: 0, y: 30 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.4 }}
        transition={{ duration: 0.7, ease: EASE }}
      >
        <h2 className="lp-close-title">Start with one photo.</h2>
        <motion.button
          className="lp-cta"
          onClick={() => navigate("/login")}
          whileHover={{ y: -2 }}
          whileTap={{ scale: 0.97 }}
        >
          Open MyCloset
        </motion.button>
      </motion.section>

      <footer className="lp-foot">
        <span>MyCloset</span>
      </footer>
    </div>
  );
}
