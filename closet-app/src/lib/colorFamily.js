/* Map a garment's colour word to one of the palette's highlight families.
 *
 * The closet skews heavily neutral -- black, grey, white, beige, cream and taupe
 * account for well over half of a typical wardrobe -- so mapping colour names
 * straight onto hues would produce a wall of grey cards. Neutrals instead get a
 * violet-slate wash that matches the app's accent, and only genuinely chromatic
 * garments take their own hue.
 */
const FAMILIES = {
  violet: { a: "#a855f7", b: "#6366f1" },
  cyan:   { a: "#22d3ee", b: "#3b82f6" },
  green:  { a: "#34d399", b: "#059669" },
  amber:  { a: "#fbbf24", b: "#f59e0b" },
  rose:   { a: "#fb7185", b: "#e11d48" },
  slate:  { a: "#8b93b8", b: "#4c5270" },
};

const RULES = [
  [/\b(navy|blue|denim|indigo|teal|turquoise|aqua)\b/, "cyan"],
  [/\b(green|olive|sage|mint|lime|emerald)\b/,          "green"],
  [/\b(red|maroon|burgundy|crimson|pink|rose|coral)\b/, "rose"],
  [/\b(purple|violet|lilac|lavender|plum|mauve)\b/,     "violet"],
  [/\b(beige|tan|taupe|brown|camel|khaki|gold|mustard|orange|rust|cream|ivory)\b/, "amber"],
];

export function colorFamily(color) {
  const c = (color || "").toLowerCase().replace(/[_-]+/g, " ");
  for (const [re, fam] of RULES) if (re.test(c)) return fam;
  return "slate";            // black, grey, white and anything unrecognised
}

/** Gradient backdrop sitting behind a garment cutout.
 *  Strong enough to read as a colour block at a glance, still dark enough that a
 *  black or white garment keeps its contrast against it. */
export function colorWash(color) {
  const { a, b } = FAMILIES[colorFamily(color)];
  return `linear-gradient(150deg, ${a}8c 0%, ${b}59 42%, ${b}1f 78%, transparent 100%)`;
}

/** Brighter variant used on hover. */
export function colorWashHover(color) {
  const { a, b } = FAMILIES[colorFamily(color)];
  return `linear-gradient(150deg, ${a}b8 0%, ${b}80 42%, ${b}33 78%, transparent 100%)`;
}

/** Saturated edge used for hover borders and accents. */
export function colorEdge(color) {
  return FAMILIES[colorFamily(color)].a;
}
