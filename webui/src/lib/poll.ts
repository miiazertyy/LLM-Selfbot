/**
 * setInterval that only runs while the page is actually being looked at.
 *
 * The panel polled on fixed timers regardless of visibility, so a minimised
 * window or a background tab kept the backend answering requests indefinitely
 * for a view nobody could see. This runs the callback on the interval while
 * visible, stops on hide, and fires once on reveal so what you come back to is
 * current rather than a full interval out of date.
 */
export function visiblePoll(fn: () => void, ms: number): () => void {
  let timer: ReturnType<typeof setInterval> | null = null;

  const start = () => {
    if (timer) return;
    timer = setInterval(fn, ms);
  };

  const stop = () => {
    if (!timer) return;
    clearInterval(timer);
    timer = null;
  };

  const onVisibility = () => {
    if (document.hidden) {
      stop();
      return;
    }
    fn(); // catch up now instead of waiting out a whole interval
    start();
  };

  if (!document.hidden) start();
  document.addEventListener("visibilitychange", onVisibility);

  return () => {
    stop();
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
