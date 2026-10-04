import { bigPictureCovering } from "./stores";

/**
 * setInterval that only runs while the page is actually being looked at.
 *
 * The panel polled on fixed timers regardless of visibility, so a minimised
 * window or a background tab kept the backend answering requests indefinitely
 * for a view nobody could see. This runs the callback on the interval while
 * visible, stops on hide, and fires once on reveal so what you come back to is
 * current rather than a full interval out of date.
 *
 * A window that is open but not in front (behind a game, on the other screen)
 * is not hidden, and was asked as often as one in use: there it asks a quarter
 * as often (twenty seconds at the least), and catches up the moment it is
 * clicked again.
 */
export function visiblePoll(fn: () => void, ms: number, opts: { underBigPicture?: boolean } = {}): () => void {
  let timer: ReturnType<typeof setInterval> | null = null;
  let covered = false;
  let away = typeof document !== "undefined" && !document.hasFocus();
  const period = () => (away ? Math.max(ms * 4, 20_000) : ms);

  const start = () => {
    if (timer) return;
    timer = setInterval(fn, period());
  };

  const stop = () => {
    if (!timer) return;
    clearInterval(timer);
    timer = null;
  };

  const onVisibility = () => {
    if (document.hidden || covered) {
      stop();
      return;
    }
    fn(); // catch up now instead of waiting out a whole interval
    start();
  };

  const onBlur = () => {
    away = true;
    if (timer) {
      stop();
      start();
    }
  };
  const onFocus = () => {
    const was = away;
    away = false;
    if (document.hidden || covered) return;
    stop();
    if (was) fn(); // back at the window: current at once
    start();
  };

  if (!document.hidden) start();
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("blur", onBlur);
  window.addEventListener("focus", onFocus);

  // A page under Big Picture cannot be seen either: it stops polling while
  // covered and catches up when uncovered, like a hidden window. Big Picture
  // loads what it shows itself; the few pollers it reads say so.
  let first = true;
  const unsub = opts.underBigPicture ? () => {} : bigPictureCovering.subscribe((on) => {
    covered = on;
    if (first) {
      first = false;
      return;
    }
    onVisibility();
  });

  return () => {
    stop();
    unsub();
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("blur", onBlur);
    window.removeEventListener("focus", onFocus);
  };
}
