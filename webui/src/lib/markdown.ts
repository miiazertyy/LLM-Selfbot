/**
 * The small slice of Markdown a persona is actually written in.
 *
 * Not a general Markdown engine, and deliberately not a dependency: what goes
 * in here is bold, italic, a heading, a list, the odd bit of code. A library
 * for that is a lot of bytes and a lot of surface for something rendered with
 * {@html}.
 *
 * Which is the important part: the output IS rendered as HTML, so everything
 * is escaped FIRST and only the tags this file emits can ever exist. The
 * persona is the user's own text, but it is also the one field an LLM writes
 * into, and "it is our own data" is exactly the assumption that turns into an
 * injection later.
 */

const ESC: Record<string, string> = {
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
};

function escape(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESC[c]);
}

/** Inline marks, applied to already-escaped text. */
function inline(s: string): string {
  return s
    // Code first: whatever is inside it must not then be read as emphasis.
    .replace(/`([^`]+)`/g, '<code class="md-code">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    // Single marks only after the double ones, or **x** loses its inner pair.
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[^_\w])_([^_\n]+)_/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>");
}

export function renderMarkdown(src: string): string {
  const lines = escape(src ?? "").split(/\r?\n/);
  const out: string[] = [];
  let list: "ul" | "ol" | null = null;
  let fenced = false;
  let fence: string[] = [];

  const closeList = () => {
    if (list) {
      out.push(`</${list}>`);
      list = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();

    if (/^\s*```/.test(line)) {
      if (fenced) {
        out.push(`<pre class="md-pre"><code>${fence.join("\n")}</code></pre>`);
        fence = [];
        fenced = false;
      } else {
        closeList();
        fenced = true;
      }
      continue;
    }
    if (fenced) {
      fence.push(line);
      continue;
    }

    if (!line.trim()) {
      closeList();
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      closeList();
      const level = heading[1].length;
      out.push(`<div class="md-h md-h${level}">${inline(heading[2])}</div>`);
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      if (list !== "ul") { closeList(); out.push('<ul class="md-ul">'); list = "ul"; }
      out.push(`<li>${inline(line.replace(/^\s*[-*+]\s+/, ""))}</li>`);
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      if (list !== "ol") { closeList(); out.push('<ol class="md-ol">'); list = "ol"; }
      out.push(`<li>${inline(line.replace(/^\s*\d+[.)]\s+/, ""))}</li>`);
      continue;
    }

    if (/^\s*&gt;\s?/.test(line)) {
      closeList();
      out.push(`<blockquote class="md-quote">${inline(line.replace(/^\s*&gt;\s?/, ""))}</blockquote>`);
      continue;
    }

    closeList();
    out.push(`<p class="md-p">${inline(line)}</p>`);
  }

  closeList();
  // An unterminated fence still has to render, or the tail of the text vanishes.
  if (fenced && fence.length) {
    out.push(`<pre class="md-pre"><code>${fence.join("\n")}</code></pre>`);
  }
  return out.join("");
}
