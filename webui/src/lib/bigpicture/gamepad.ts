/**
 * Big Picture from the sofa: a gamepad does what the keys do.
 *
 * The standard layout every browser agrees on (A 0, B 1, X 2, Y 3, LB 4, RB 5,
 * Back 8, Start 9, the D-pad 12 to 15), and the left stick for the D-pad. A
 * direction held down repeats, the first time after a pause, as a key does.
 * Nothing runs until a pad has been seen, and then one look a frame, and only
 * while one stays connected.
 */
export type PadCommand = "up" | "down" | "left" | "right" | "ok" | "back" | "reply" | "hide" | "prev" | "next" | "stay" | "keys";

const BUTTONS: Partial<Record<number, PadCommand>> = {
  0: "ok", 1: "back", 2: "reply", 3: "hide", 4: "prev", 5: "next", 8: "keys", 9: "stay",
  12: "up", 13: "down", 14: "left", 15: "right",
};
const DIRECTIONS = new Set<PadCommand>(["up", "down", "left", "right"]);
const FIRST_REPEAT = 380;
const NEXT_REPEAT = 130;
const STICK = 0.55;

export function startGamepad(on: (cmd: PadCommand) => void): () => void {
  let frame = 0;
  const held = new Map<PadCommand, number>();

  const pads = () => (navigator.getGamepads?.() ?? []).filter((p): p is Gamepad => !!p);
  function look(t: number) {
    frame = 0;
    const all = pads();
    if (!all.length) return;
    const down = new Set<PadCommand>();
    for (const pad of all) {
      pad.buttons.forEach((b, i) => {
        const cmd = BUTTONS[i];
        if (cmd && b.pressed) down.add(cmd);
      });
      const [x = 0, y = 0] = pad.axes;
      if (x < -STICK) down.add("left");
      if (x > STICK) down.add("right");
      if (y < -STICK) down.add("up");
      if (y > STICK) down.add("down");
    }
    for (const cmd of down) {
      const due = held.get(cmd);
      if (due === undefined) {
        held.set(cmd, DIRECTIONS.has(cmd) ? t + FIRST_REPEAT : Infinity);
        on(cmd);
      } else if (t >= due) {
        held.set(cmd, t + NEXT_REPEAT);
        on(cmd);
      }
    }
    for (const cmd of [...held.keys()]) if (!down.has(cmd)) held.delete(cmd);
    frame = requestAnimationFrame(look);
  }
  const wake = () => {
    if (!frame) frame = requestAnimationFrame(look);
  };
  window.addEventListener("gamepadconnected", wake);
  if (pads().length) wake();
  return () => {
    window.removeEventListener("gamepadconnected", wake);
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  };
}

/** A small bump in the hands, for something done: a reply gone out, a friend accepted. Where a pad can. */
export function rumble(strength = 0.35) {
  for (const pad of navigator.getGamepads?.() ?? []) {
    pad?.vibrationActuator?.playEffect?.("dual-rumble", { duration: 70, weakMagnitude: strength, strongMagnitude: strength * 0.5 })
      ?.catch?.(() => {});
  }
}
