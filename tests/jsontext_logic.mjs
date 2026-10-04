/**
 * The raw config editor's tidying and checking (webui/src/lib/jsontext.ts),
 * run for real under Node.
 */
const j = await import("../webui/src/lib/jsontext.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const messy = '{"bot":{"owner_id":272402839874174976,"prefix":"/","models":["a","b"],"empty":{},"none":[],"x":null,"t":true,"f":1.50e3,"s":"a, b: {c} [d] \\"q\\""}}';
const tidy = j.formatJson(messy);
check("a big ID comes out exactly as it went in, not rounded", tidy.includes("272402839874174976"), tidy);
check("and the text still means the same", JSON.stringify(JSON.parse(tidy)) === JSON.stringify(JSON.parse(messy)));
check("numbers keep their own spelling", tidy.includes("1.50e3"));
check("strings with commas, colons and brackets inside are left alone", tidy.includes('"a, b: {c} [d] \\"q\\""'));
check("indented two spaces a level", tidy.includes('\n  "bot": {\n    "owner_id": 272402839874174976,'), tidy.slice(0, 80));
check("empty ones stay on their line", tidy.includes('"empty": {}') && tidy.includes('"none": []'));
check("tidying tidy text changes nothing", j.formatJson(tidy) === tidy);
check("text that is not JSON is not tidied", j.formatJson('{"a": 1,}') === null);

check("JSON is fine", j.jsonError(tidy) === null);
const bad = '{\n  "a": 1\n  "b": 2\n}';
const p = j.jsonError(bad);
check("a missing comma is found on the line it is missing from, not the next", p && p.line === 2, JSON.stringify(p));
check("and said plainly, short enough for the pill", p && p.message === "Missing comma", p && p.message);
const quote = j.jsonError('{"a": "open}');
check("an unclosed quote is said as one", quote && /quote/i.test(quote.message), JSON.stringify(quote));
const extra = j.jsonError('{"a": 1,}');
check("a comma too many is said as one", extra && /extra comma/i.test(extra.message), JSON.stringify(extra));
const words = ["Missing comma", "Extra comma or unquoted name", "Quote never closed", "Line break inside quotes",
               "Text after the last brace", "Ends too soon", "Missing colon"];
check("every message is short enough to fit the pill whole", words.every((w) => w.length <= 30));
const cut = j.jsonError('{"a": [1, 2');
check("text that stops short says so", cut && cut.message.length > 0, JSON.stringify(cut));

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
