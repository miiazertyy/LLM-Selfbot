/**
 * Discord's message formatting, drawn the way Discord draws it.
 *
 * Messages in the Chats tab were shown as raw text, so formatting came through
 * as literal asterisks and pipes. This renders the part of Discord's markdown
 * people actually use: bold, italic, underline (Discord's __ is underline, not
 * bold), strikethrough, spoilers, inline code and code blocks, quotes, small
 * headings and lists, links, and custom emoji.
 *
 * The output is inserted as HTML, so the text is escaped FIRST and only the
 * tags produced here can exist. Links are only ever http(s), so no javascript:
 * or data: URL can be made from a message. Mentions are not handled here: the
 * caller splits them out first (lib/mentions.ts) so they become real,
 * clickable names.
 */

const ESC: Record<string, string> = {
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
};

function escape(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESC[c]);
}

// A URL in already-escaped text: stops at whitespace, and before an escaped
// quote or angle bracket, so "see <https://x.com>" does not swallow the entity.
const URL_RE = /https?:\/\/(?:(?!&quot;|&lt;|&gt;|&#39;)[^\s<])+/g;

export function discordInline(src: string): string {
  let s = escape(src ?? "");

  // Code first, and held aside, so nothing inside it is read as formatting.
  const blocks: string[] = [];
  s = s.replace(/```(?:[a-z0-9_+-]+\n)?([\s\S]*?)```/gi, (_, code) => {
    blocks.push(code.replace(/^\n+|\n+$/g, ""));
    return `\u0000B${blocks.length - 1}\u0000`;
  });
  const codes: string[] = [];
  s = s.replace(/`([^`\n]+)`/g, (_, code) => {
    codes.push(code);
    return `\u0000C${codes.length - 1}\u0000`;
  });

  // Links before emphasis, held aside too, or an underscore in a URL turns
  // half of it italic.
  const links: string[] = [];
  s = s.replace(URL_RE, (url) => {
    // Trailing punctuation belongs to the sentence, not the link.
    const m = url.match(/^(.*?)([.,:;!?)\]]*)$/);
    const href = m ? m[1] : url;
    const tail = m ? m[2] : "";
    links.push(href);
    return `\u0000L${links.length - 1}\u0000${tail}`;
  });

  s = s
    .replace(/\|\|([\s\S]+?)\|\|/g, '<span class="dm-spoiler" tabindex="0" title="Spoiler">$1</span>')
    .replace(/\*\*\*([^*\n]+)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n]+)__/g, "<u>$1</u>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?![\w*])/g, "$1<em>$2</em>")
    .replace(/(^|[^_\w])_([^_\n]+)_(?![\w_])/g, "$1<em>$2</em>")
    .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
    // Custom emoji, as escaped text: &lt;:name:id&gt; or &lt;a:name:id&gt;.
    .replace(/&lt;(a?):(\w{2,32}):(\d{15,21})&gt;/g, (_, a, name, id) =>
      `<img class="dm-emoji" alt=":${name}:" title=":${name}:" loading="lazy" ` +
      `src="https://cdn.discordapp.com/emojis/${id}.${a ? "gif" : "webp"}?size=48">`);

  // Line-level marks: quotes, small headings, list items.
  s = s
    .split("\n")
    .map((line) => {
      if (/^&gt;&gt;&gt; /.test(line)) return `<span class="dm-quote">${line.slice(13)}</span>`;
      if (/^&gt; /.test(line)) return `<span class="dm-quote">${line.slice(5)}</span>`;
      const h = line.match(/^(#{1,3}) (.+)$/);
      if (h) return `<span class="dm-h dm-h${h[1].length}">${h[2]}</span>`;
      const li = line.match(/^\s*[-*] (.+)$/);
      if (li) return `<span class="dm-li">${li[1]}</span>`;
      return line;
    })
    .join("\n");

  s = s.replace(/\u0000L(\d+)\u0000/g, (_, i) =>
    `<a class="dm-link" href="${links[+i]}" target="_blank" rel="noopener noreferrer">${links[+i]}</a>`);
  s = s.replace(/\u0000C(\d+)\u0000/g, (_, i) => `<code class="dm-code">${codes[+i]}</code>`);
  s = s.replace(/\u0000B(\d+)\u0000/g, (_, i) => `<pre class="dm-pre">${blocks[+i]}</pre>`);
  return s;
}
