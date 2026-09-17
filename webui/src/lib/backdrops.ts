/**
 * Living backgrounds.
 *
 * Every one of these is CSS drawn from the theme's own custom properties, so
 * they take on whatever palette is selected instead of needing an asset per
 * theme. That also rules out shipping a GIF: a fixed image cannot follow the
 * colours, weighs far more than a few gradients, and cannot be paused when
 * someone turns motion off.
 *
 * They animate transform and opacity only, which the compositor handles on its
 * own, so an idle window costs nothing measurable - the point of the work that
 * went into stopping the snow canvas running forever.
 */

export type Backdrop = {
  id: string;
  name: string;
  hint: string;
};

export const BACKDROPS: Backdrop[] = [
  { id: "none", name: "Flat", hint: "Just the theme colour" },
  { id: "aurora", name: "Aurora", hint: "Slow drifting light in the accent colours" },
  { id: "nebula", name: "Nebula", hint: "A deep rotating haze" },
  { id: "drift", name: "Drift", hint: "Orbs rising quietly" },
];

/** How many orbs the drift backdrop renders. */
export const DRIFT_ORBS = 14;
