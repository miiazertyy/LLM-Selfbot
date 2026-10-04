/**
 * Putting a picture on the clipboard.
 *
 * The clipboard only takes PNG, so anything else is redrawn through a canvas
 * first. Shared by the Pictures page and the profile-picture viewer so the
 * behaviour, and the message when a browser refuses, is the same in both.
 */

/** Re-encode any image blob as PNG, which is the one type the clipboard takes. */
export function toPng(blob: Blob): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const ctx = c.getContext("2d");
      if (!ctx) {
        URL.revokeObjectURL(url);
        return reject(new Error("no canvas context"));
      }
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      c.toBlob((out) => (out ? resolve(out) : reject(new Error("could not redraw it"))), "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("could not read the picture"));
    };
    img.crossOrigin = "anonymous";
    img.src = url;
  });
}

/** Copy the picture at `url`. Throws with something worth showing on failure. */
export async function copyImageFrom(url: string): Promise<void> {
  let blob: Blob;
  try {
    blob = await fetch(url, { referrerPolicy: "no-referrer" }).then((r) => {
      if (!r.ok) throw new Error(`the picture could not be fetched (${r.status})`);
      return r.blob();
    });
  } catch (e: any) {
    throw new Error(e?.message || "could not fetch the picture");
  }
  const png = blob.type === "image/png" ? blob : await toPng(blob);
  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
  } catch (e: any) {
    // Some browsers have no image clipboard at all; say what to do instead of
    // reporting an error name nobody can act on.
    if (e?.name === "ReferenceError" || e?.name === "TypeError") {
      throw new Error("This browser will not let a page copy an image. Right click the picture itself and use Copy image.");
    }
    throw e;
  }
}
