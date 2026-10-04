/**
 * A Memory summary, as blocks to draw: a headline, then short labelled points.
 *
 * The model is asked for exactly that shape (summary_instructions in
 * app/utils/ai.py):
 *
 *   **Planning Saturday at the lake**
 *   - **Plans:** leaving at 8, Ana drives
 *   - **Vibe:** easy, lots of jokes
 *   - **Waiting on:** you, for the time
 *
 * Models drift a little (a # heading instead of bold, "*" or "•" for bullets,
 * "**Plans**:" with the colon outside, a headline left plain), so each of those
 * reads the same way. A summary written before this shape was asked for is
 * plain prose and comes out as paragraphs. Inline marks go through
 * discordInline, which escapes the text before it adds any tag of its own.
 */
import { discordInline } from "./discordmd";

export type SummaryBlock =
  | { kind: "lead"; html: string }
  | { kind: "point"; label: string; html: string }
  | { kind: "para"; html: string };

const BULLET = /^(?:[-*•]|\d{1,2}[.)])\s+/;
/** A line that is all bold: the headline. */
const ALL_BOLD = /^\*\*([^*]+)\*\*[.:]?$/;
/** "**Plans:** rest" or "**Plans**: rest": a bold label, then what it says. */
const LABEL = /^\*\*([^*:]{1,24}?)\s*:?\s*\*\*\s*:?\s+/;

export function summaryBlocks(text: string): SummaryBlock[] {
  const lines = (text ?? "")
    .replace(/\r/g, "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const out: SummaryBlock[] = [];
  lines.forEach((line, i) => {
    const heading = /^#{1,6}\s+/.test(line);
    const plain = line.replace(/^#{1,6}\s+/, "");
    const bullet = BULLET.test(plain);

    // The headline: the first line, when it is bold, a heading, or short with points after it.
    if (!out.length && !bullet) {
      const bold = ALL_BOLD.exec(plain);
      if (bold || heading || (plain.length <= 90 && BULLET.test(lines[i + 1] ?? ""))) {
        out.push({ kind: "lead", html: discordInline((bold?.[1] ?? plain).trim()) });
        return;
      }
    }
    if (bullet) {
      const body = plain.replace(BULLET, "");
      const m = LABEL.exec(body);
      // A label is a word or three; anything longer was a bold phrase that opens a sentence.
      const label = m && m[1].trim().split(/\s+/).length <= 3 ? m[1].trim() : "";
      out.push({ kind: "point", label, html: discordInline(label && m ? body.slice(m[0].length) : body) });
      return;
    }
    out.push({ kind: "para", html: discordInline(plain) });
  });
  return out;
}
