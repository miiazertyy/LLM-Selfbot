/**
 * A field as wide as what is typed in it, and no wider: it grows with each
 * letter and shrinks back as they go, so there is never a run of empty field
 * after the words. A fixed box left a "/" alone at the start of a long empty
 * well.
 *
 * Measured off a hidden twin given the field's own font, letter spacing,
 * padding and border, so it is right for any typeface the app is set to.
 * Empty, its placeholder is measured instead. Growing is immediate, in the
 * same frame as the letter, or the new letter would show cut off for a moment
 * while the width caught up; shrinking eases (the `is-auto` transition in
 * app.css). Never wider than its row allows: CSS max-width still holds, and
 * the text scrolls inside it past that.
 *
 * `value` is passed in so a change made from outside (an undo, a reset, a
 * save from elsewhere) resizes it too.
 */

type Options = { value?: unknown; min?: number };

let twin: HTMLSpanElement | null = null;

function measure(node: HTMLInputElement, text: string): number {
  if (!twin) {
    twin = document.createElement("span");
    twin.setAttribute("aria-hidden", "true");
    Object.assign(twin.style, {
      position: "absolute", left: "-9999px", top: "0", visibility: "hidden", whiteSpace: "pre", pointerEvents: "none",
    });
    document.body.appendChild(twin);
  }
  const cs = getComputedStyle(node);
  // Each property on its own: the `font` shorthand reads back empty when a typeface sets something it cannot say
  // (feature or variation settings), and the twin would then measure in the page's font instead.
  for (const k of ["fontFamily", "fontSize", "fontWeight", "fontStyle", "fontStretch", "fontVariant", "fontVariantNumeric",
                   "fontFeatureSettings", "fontVariationSettings", "fontKerning", "letterSpacing", "wordSpacing",
                   "textTransform"] as const) {
    (twin.style as any)[k] = cs[k];
  }
  twin.textContent = text;
  const chrome = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight)
    + parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth);
  // Room for the caret after the last letter.
  return Math.ceil(twin.getBoundingClientRect().width + chrome + 2);
}

export function autowidth(node: HTMLInputElement, options: Options = {}) {
  let min = options.min ?? 0;
  let raf = 0;

  /** `instant`: the first fit, and the one after the typeface loads, never animate (the page would open shrinking). */
  function fit(instant = false) {
    const text = node.value || node.placeholder || "";
    const want = Math.max(min, measure(node, text));
    const now = node.getBoundingClientRect().width;
    // Growing in the same frame; shrinking eased by the class's transition.
    node.classList.toggle("is-growing", instant || want > now + 0.5);
    node.style.width = `${want}px`;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => node.classList.remove("is-growing"));
  }
  const onInput = () => fit();

  node.classList.add("is-auto");
  node.addEventListener("input", onInput);
  fit(true);
  // The app's typeface may still be loading: measured again once it is in.
  document.fonts?.ready.then(() => node.isConnected && fit(true)).catch(() => {});

  return {
    update(next: Options = {}) {
      min = next.min ?? 0;
      // Typed here already measured; a value set from outside is measured now.
      queueMicrotask(() => fit());
    },
    destroy() {
      cancelAnimationFrame(raf);
      node.removeEventListener("input", onInput);
    },
  };
}
