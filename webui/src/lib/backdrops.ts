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
};

// Aurora first: it is the default, so the look a new install has is the first one offered.
export const BACKDROPS: Backdrop[] = [
  { id: "aurora", name: "Aurora" },
  { id: "none", name: "Flat" },
  { id: "nebula", name: "Nebula" },
  { id: "ripple", name: "Ripple" },
];

/** How many rings the ripple backdrop renders. */
export const RIPPLE_RINGS = 5;
