/**
 * JSON as text, for the raw config editor: tidied and checked without ever
 * being turned into values and back.
 *
 * The config holds a Discord ID past 2^53, so JSON.parse then JSON.stringify
 * would round it, and saving would write the rounded one (see Settings'
 * openRaw). Formatting here re-indents the text token by token: every number,
 * string and literal comes out exactly as it went in.
 */

/** `text` re-indented, or null when it is not valid JSON (nothing to tidy then). */
export function formatJson(text: string, indent = 2): string | null {
  if (jsonError(text)) return null;
  const pad = (depth: number) => "\n" + " ".repeat(depth * indent);
  let out = "";
  let depth = 0;
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === '"') {
      let j = i + 1;
      while (j < text.length && text[j] !== '"') j += text[j] === "\\" ? 2 : 1;
      out += text.slice(i, j + 1);
      i = j + 1;
    } else if (c === " " || c === "\n" || c === "\r" || c === "\t") {
      i++;
    } else if (c === "{" || c === "[") {
      // An empty one stays on its line: {} and [], not a brace on each of two.
      let k = i + 1;
      while (k < text.length && /\s/.test(text[k])) k++;
      if (text[k] === (c === "{" ? "}" : "]")) {
        out += c + text[k];
        i = k + 1;
      } else {
        depth++;
        out += c + pad(depth);
        i++;
      }
    } else if (c === "}" || c === "]") {
      depth = Math.max(0, depth - 1);
      out += pad(depth) + c;
      i++;
    } else if (c === ",") {
      out += "," + pad(depth);
      i++;
    } else if (c === ":") {
      out += ": ";
      i++;
    } else {
      let j = i;
      while (j < text.length && !/[\s,:[\]{}"]/.test(text[j])) j++;
      out += text.slice(i, Math.max(j, i + 1));
      i = Math.max(j, i + 1);
    }
  }
  return out + "\n";
}

export type JsonProblem = { message: string; pos: number; line: number; col: number };

/** The parser's words, said plainly; the third says the fault is before where it was noticed. */
const PLAIN: [RegExp, string, boolean?][] = [
  [/Expected ',' or '[}\]]' after (property value|array element)/i, "Missing comma", true],
  [/Expected double-quoted property name/i, "Extra comma or unquoted name"],
  [/Expected property name or '}'/i, "Extra comma or unquoted name"],
  [/Unterminated string/i, "Quote never closed"],
  [/Bad control character in string/i, "Line break inside quotes"],
  [/Unexpected non-whitespace character after JSON/i, "Text after the last brace"],
  [/Unexpected end of JSON input/i, "Ends too soon"],
  [/Expected ':' after property name/i, "Missing colon"],
];

/** Where `text` stops being JSON, in words and as a place; null when it is JSON. */
export function jsonError(text: string): JsonProblem | null {
  try {
    JSON.parse(text);
    return null;
  } catch (e: any) {
    const raw = String(e?.message ?? "Not valid JSON");
    const at = /position (\d+)/.exec(raw);
    let pos = at ? Number(at[1]) : text.length;
    pos = Math.max(0, Math.min(text.length, pos));
    // "Expected ',' or '}' after property value in JSON at position 312 (line 12 column 5)"
    // reads better as just the first half, with the place said once, by us.
    let message = raw.replace(/\s*in JSON at position \d+.*$/i, "").replace(/\s*\(line \d+ column \d+\)$/i, "");
    message = message.replace(/^JSON\.parse:\s*/i, "");
    const plain = PLAIN.find(([pattern]) => pattern.test(message));
    if (plain) {
      message = plain[1];
      // A missing comma is noticed at the next line, but belongs at the end
      // of the one before: point there.
      if (plain[2]) {
        let back = pos;
        while (back > 0 && /\s/.test(text[back - 1])) back--;
        pos = back;
      }
    }
    const before = text.slice(0, pos);
    const line = before.split("\n").length;
    const col = pos - before.lastIndexOf("\n");
    return { message: message.charAt(0).toUpperCase() + message.slice(1), pos, line, col };
  }
}
