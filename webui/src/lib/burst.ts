/**
 * An emoji picked, popping up out of where it was pressed and floating off, a
 * ring going out under it: reacting to a message, a reaction added to the set.
 * Drawn on the page itself, so the picker it came from can close at once.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";

export function burst(ch: string, from: Element | null) {
  if (!from || !get(motionEnabled)) return;
  const r = from.getBoundingClientRect();
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  const fly = document.createElement("span");
  fly.className = "emoji-burst";
  fly.textContent = ch;
  fly.style.left = `${x}px`;
  fly.style.top = `${y}px`;
  const ring = document.createElement("span");
  ring.className = "emoji-burst-ring";
  ring.style.left = `${x}px`;
  ring.style.top = `${y}px`;
  document.body.append(ring, fly);
  fly.animate([
    { transform: "translate(-50%, -50%) scale(1)", opacity: 1 },
    { transform: "translate(-50%, -110%) scale(1.9)", opacity: 1, offset: 0.35 },
    { transform: "translate(-50%, -190%) scale(1.5)", opacity: 0 },
  ], { duration: 620, easing: "cubic-bezier(0.2, 0.8, 0.3, 1)" }).finished.then(() => fly.remove(), () => fly.remove());
  ring.animate([
    { transform: "translate(-50%, -50%) scale(0.4)", opacity: 0.9 },
    { transform: "translate(-50%, -50%) scale(1.6)", opacity: 0 },
  ], { duration: 480, easing: "cubic-bezier(0.2, 0.7, 0.3, 1)" }).finished.then(() => ring.remove(), () => ring.remove());
}
