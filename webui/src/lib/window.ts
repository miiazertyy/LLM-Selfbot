/**
 * Frameless-window controls.
 *
 * The desktop shell runs pywebview with frameless=True, so there is no OS title
 * bar and the app content fills the window. These helpers drive the window
 * through pywebview's JS bridge. In a plain browser (remote access over
 * Tailscale, say) `available` is false and the chrome hides itself.
 */

type PyApi = {
  minimize?: () => Promise<void>;
  close_window?: () => Promise<void>;
  set_size?: (w: number, h: number) => Promise<void>;
  get_size?: () => Promise<[number, number]>;
};

declare global {
  interface Window {
    pywebview?: { api?: PyApi };
  }
}

let ready = false;

/** pywebview injects its bridge asynchronously; wait for it once at startup. */
export function waitForBridge(timeout = 3000): Promise<boolean> {
  return new Promise((resolve) => {
    if (window.pywebview?.api) {
      ready = true;
      return resolve(true);
    }
    const started = Date.now();
    const poll = setInterval(() => {
      if (window.pywebview?.api) {
        clearInterval(poll);
        ready = true;
        resolve(true);
      } else if (Date.now() - started > timeout) {
        clearInterval(poll);
        resolve(false);
      }
    }, 60);
  });
}

export function isDesktop(): boolean {
  return ready && !!window.pywebview?.api;
}

export async function minimize(): Promise<void> {
  try {
    await window.pywebview?.api?.minimize?.();
  } catch {
    /* bridge went away, nothing sensible to do */
  }
}

export async function closeWindow(): Promise<void> {
  try {
    await window.pywebview?.api?.close_window?.();
  } catch {
    /* ignore */
  }
}

/** Resize the window to an exact size (pocket <-> desk toggle). */
export async function setSize(w: number, h: number): Promise<void> {
  try {
    await window.pywebview?.api?.set_size?.(Math.round(w), Math.round(h));
  } catch {
    /* ignore */
  }
}

/**
 * Drive a corner resize. Frameless windows lose the native resize border, so
 * the grip streams sizes to Python, throttled to one call per frame.
 */
export function startResize(e: PointerEvent): void {
  if (!isDesktop()) return;
  e.preventDefault();

  const startX = e.screenX;
  const startY = e.screenY;
  const startW = window.outerWidth || window.innerWidth;
  const startH = window.outerHeight || window.innerHeight;
  let queued: { w: number; h: number } | null = null;
  let frame = 0;

  const flush = () => {
    frame = 0;
    if (!queued) return;
    const { w, h } = queued;
    queued = null;
    window.pywebview?.api?.set_size?.(w, h)?.catch(() => {});
  };

  const move = (ev: PointerEvent) => {
    queued = {
      w: Math.max(720, Math.round(startW + (ev.screenX - startX))),
      h: Math.max(480, Math.round(startH + (ev.screenY - startY))),
    };
    if (!frame) frame = requestAnimationFrame(flush);
  };

  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    if (frame) cancelAnimationFrame(frame);
    flush();
    document.body.style.cursor = "";
  };

  document.body.style.cursor = "nwse-resize";
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

/**
 * Save text to a file the user chooses.
 *
 * In the desktop shell a browser download is an anchor with a download
 * attribute, and the embedded WebView has no download handler: clicking
 * Download did nothing, with nowhere to pick. The native dialog is used there,
 * and a normal browser download everywhere else.
 *
 * Returns the path written, or "" when the user cancelled.
 */
export async function saveTextFile(filename: string, content: string): Promise<string> {
  const api = (window as any).pywebview?.api;
  if (api?.save_text_file) {
    const result = await api.save_text_file(filename, content);
    if (typeof result === "string" && result.startsWith("error:")) {
      throw new Error(result.slice(6).trim());
    }
    return result || "";
  }

  // Browser: an anchor has to be in the document for some engines to honour
  // the click, and the object URL must outlive the click itself.
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 1000);
  return filename;
}

/** A folder chosen by the user. Desktop only; "" elsewhere or when cancelled. */
export async function pickFolder(): Promise<string> {
  const api = (window as any).pywebview?.api;
  if (!api?.pick_folder) return "";
  return (await api.pick_folder()) || "";
}

/** One existing file chosen by the user. Desktop only. */
export async function pickFile(extensions?: string[]): Promise<string> {
  const api = (window as any).pywebview?.api;
  if (!api?.pick_file) return "";
  return (await api.pick_file(extensions ?? null)) || "";
}


/**
 * Open a link outside the app.
 *
 * In the desktop shell there is no tab to open one in: pywebview's window is
 * the app, so window.open either does nothing or navigates the panel away from
 * itself. The backend opens it in the real browser instead, by name, because
 * that endpoint runs on the host machine and must not be an "open any URL"
 * service. In an ordinary browser, including a phone reaching the panel over
 * Tailscale, the browser opens its own link and the host is not involved.
 */
export async function openExternal(name: string, url: string): Promise<void> {
  if (isDesktop()) {
    try {
      await fetch("/api/system/link", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name }),
      });
      return;
    } catch {
      /* fall through and try the window, which is better than nothing */
    }
  }
  window.open(url, "_blank", "noopener");
}
