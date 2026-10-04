/**
 * Languages, for the two settings that name one.
 *
 * Persona locale (bot.locale) is the language the account's Discord is set
 * to. It goes out as the X-Discord-Locale header on every request, so it has
 * to be one of the codes Discord itself offers ("en-US", "pt-BR", "fr"), not
 * just any language tag: Discord's own client never sends anything else.
 *
 * Fallback language (bot.default_language) is what a reply is written in
 * until the person's own language has been detected. The detector answers
 * with a two-letter ISO 639-1 code, so every one of those is offered.
 *
 * Plain data and functions (Intl aside), so they run under Node in tests.
 */

export type Lang = {
  /** What is stored: "en-US", "fr". */
  code: string;
  /** In English, like the rest of the app: "French". */
  name: string;
  /** In itself: "Français". */
  native: string;
  /** A country whose flag stands for it, where one does; Discord's own picker shows these. */
  flag?: string;
};

/**
 * Discord's languages, as its own settings list them: the code it sends, the
 * name in English and in the language itself, and the flag beside it.
 * Latin American Spanish is a region, not a country, so it has no flag.
 */
export const DISCORD_LOCALES: Lang[] = [
  { code: "id", name: "Indonesian", native: "Bahasa Indonesia", flag: "ID" },
  { code: "da", name: "Danish", native: "Dansk", flag: "DK" },
  { code: "de", name: "German", native: "Deutsch", flag: "DE" },
  { code: "en-GB", name: "English, UK", native: "English, UK", flag: "GB" },
  { code: "en-US", name: "English, US", native: "English, US", flag: "US" },
  { code: "es-ES", name: "Spanish", native: "Español", flag: "ES" },
  { code: "es-419", name: "Spanish, Latin America", native: "Español, LATAM" },
  { code: "fr", name: "French", native: "Français", flag: "FR" },
  { code: "hr", name: "Croatian", native: "Hrvatski", flag: "HR" },
  { code: "it", name: "Italian", native: "Italiano", flag: "IT" },
  { code: "lt", name: "Lithuanian", native: "Lietuviškai", flag: "LT" },
  { code: "hu", name: "Hungarian", native: "Magyar", flag: "HU" },
  { code: "nl", name: "Dutch", native: "Nederlands", flag: "NL" },
  { code: "no", name: "Norwegian", native: "Norsk", flag: "NO" },
  { code: "pl", name: "Polish", native: "Polski", flag: "PL" },
  { code: "pt-BR", name: "Portuguese, Brazil", native: "Português do Brasil", flag: "BR" },
  { code: "ro", name: "Romanian", native: "Română", flag: "RO" },
  { code: "fi", name: "Finnish", native: "Suomi", flag: "FI" },
  { code: "sv-SE", name: "Swedish", native: "Svenska", flag: "SE" },
  { code: "vi", name: "Vietnamese", native: "Tiếng Việt", flag: "VN" },
  { code: "tr", name: "Turkish", native: "Türkçe", flag: "TR" },
  { code: "cs", name: "Czech", native: "Čeština", flag: "CZ" },
  { code: "el", name: "Greek", native: "Ελληνικά", flag: "GR" },
  { code: "bg", name: "Bulgarian", native: "Български", flag: "BG" },
  { code: "ru", name: "Russian", native: "Русский", flag: "RU" },
  { code: "uk", name: "Ukrainian", native: "Українська", flag: "UA" },
  { code: "hi", name: "Hindi", native: "हिन्दी", flag: "IN" },
  { code: "th", name: "Thai", native: "ไทย", flag: "TH" },
  { code: "zh-CN", name: "Chinese, China", native: "中文", flag: "CN" },
  { code: "ja", name: "Japanese", native: "日本語", flag: "JP" },
  { code: "zh-TW", name: "Chinese, Taiwan", native: "繁體中文", flag: "TW" },
  { code: "ko", name: "Korean", native: "한국어", flag: "KR" },
];

/** Every ISO 639-1 language: the two-letter codes the language detector answers with. */
export const LANGUAGE_CODES = (
  "aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee " +
  "el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io " +
  "is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn " +
  "mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se " +
  "sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo " +
  "wa wo xh yi yo za zh zu"
).split(" ");

/**
 * The flag each language is shown with: the country most tied to it (French
 * the French flag, English the British one, Welsh the Welsh one). The few
 * that are no country's (Esperanto and the other made-up ones, the ancient
 * and liturgical ones, Tibetan, Yiddish) have none and are shown with a
 * globe, as Latin American Spanish is in Discord's list.
 */
const FLAG_OF: Record<string, string> = {
  aa: "ET", ab: "GE", af: "ZA", ak: "GH", am: "ET", an: "ES", ar: "SA", as: "IN", av: "RU", ay: "BO",
  az: "AZ", ba: "RU", be: "BY", bg: "BG", bi: "VU", bm: "ML", bn: "BD", br: "FR", bs: "BA", ca: "AD",
  ce: "RU", ch: "GU", co: "FR", cr: "CA", cs: "CZ", cv: "RU", cy: "GB-WLS", da: "DK", de: "DE", dv: "MV",
  dz: "BT", ee: "GH", el: "GR", en: "GB", es: "ES", et: "EE", eu: "ES", fa: "IR", ff: "SN", fi: "FI",
  fj: "FJ", fo: "FO", fr: "FR", fy: "NL", ga: "IE", gd: "GB-SCT", gl: "ES", gn: "PY", gu: "IN", gv: "IM",
  ha: "NG", he: "IL", hi: "IN", ho: "PG", hr: "HR", ht: "HT", hu: "HU", hy: "AM", hz: "NA", id: "ID",
  ig: "NG", ii: "CN", ik: "US", is: "IS", it: "IT", iu: "CA", ja: "JP", jv: "ID", ka: "GE", kg: "CD",
  ki: "KE", kj: "NA", kk: "KZ", kl: "GL", km: "KH", kn: "IN", ko: "KR", kr: "NG", ks: "IN", ku: "IQ",
  kv: "RU", kw: "GB", ky: "KG", la: "VA", lb: "LU", lg: "UG", li: "NL", ln: "CD", lo: "LA", lt: "LT",
  lu: "CD", lv: "LV", mg: "MG", mh: "MH", mi: "NZ", mk: "MK", ml: "IN", mn: "MN", mr: "IN", ms: "MY",
  mt: "MT", my: "MM", na: "NR", nb: "NO", nd: "ZW", ne: "NP", ng: "NA", nl: "NL", nn: "NO", no: "NO",
  nr: "ZA", nv: "US", ny: "MW", oc: "FR", oj: "CA", om: "ET", or: "IN", os: "RU", pa: "IN", pl: "PL",
  ps: "AF", pt: "PT", qu: "PE", rm: "CH", rn: "BI", ro: "RO", ru: "RU", rw: "RW", sa: "IN", sc: "IT",
  sd: "PK", se: "NO", sg: "CF", si: "LK", sk: "SK", sl: "SI", sm: "WS", sn: "ZW", so: "SO", sq: "AL",
  sr: "RS", ss: "SZ", st: "LS", su: "ID", sv: "SE", sw: "TZ", ta: "IN", te: "IN", tg: "TJ", th: "TH",
  ti: "ER", tk: "TM", tl: "PH", tn: "BW", to: "TO", tr: "TR", ts: "ZA", tt: "RU", tw: "GH", ty: "PF",
  ug: "CN", uk: "UA", ur: "PK", uz: "UZ", ve: "ZA", vi: "VN", wa: "BE", wo: "SN", xh: "ZA", yo: "NG",
  za: "CN", zh: "CN", zu: "ZA",
};
/** The languages that are no country's, and so have a globe rather than a flag. */
export const NO_FLAG = ["ae", "bo", "cu", "eo", "ia", "ie", "io", "pi", "vo", "yi"];

/** The languages the app has always named itself, first in the list: what people mostly pick. */
export const COMMON_LANGUAGES = ["en", "fr", "es", "de", "pt", "it", "nl", "ar", "ru", "ja", "zh", "ko", "tr", "pl", "sv"];

const namers = new Map<string, Intl.DisplayNames | null>();
/** A language's name in `locale`, or "" when the runtime has none. */
function nameIn(locale: string, code: string): string {
  let n = namers.get(locale);
  if (n === undefined) {
    try {
      n = new Intl.DisplayNames([locale], { type: "language" });
    } catch {
      n = null;
    }
    namers.set(locale, n);
  }
  try {
    const out = n?.of(code) ?? "";
    return out && out !== code ? out : "";
  } catch {
    return "";
  }
}

/** "Français" rather than "français": a name at the start of a line, as a picker shows it. */
const lead = (s: string) => (s ? s.charAt(0).toLocaleUpperCase() + s.slice(1) : s);

let every: Lang[] | null = null;
/** Every ISO 639-1 language, named in English and in itself, in English alphabetical order. */
export function allLanguages(): Lang[] {
  if (!every) {
    every = LANGUAGE_CODES.map((code) => {
      const name = nameIn("en", code) || code.toUpperCase();
      return { code, name, native: lead(nameIn(code, code)) || name, flag: FLAG_OF[code] };
    }).sort((a, b) => a.name.localeCompare(b.name, "en"));
  }
  return every;
}

/** Lowercase, with accents taken off, so "francais" finds "Français". */
export const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Languages matching what was typed, by name, native name or code, closest first. */
export function searchLanguages(list: Lang[], q: string): Lang[] {
  const s = fold(q.trim());
  if (!s) return list;
  const scored: [Lang, number][] = [];
  for (const l of list) {
    const name = fold(l.name), native = fold(l.native), code = l.code.toLowerCase();
    let score = -1;
    if (code === s) score = 0;
    else if (name.startsWith(s) || native.startsWith(s)) score = 1;
    else if (code.startsWith(s)) score = 2;
    else if (name.includes(s) || native.includes(s)) score = 3;
    if (score >= 0) scored.push([l, score]);
  }
  return scored.sort((a, b) => a[1] - b[1]).map(([l]) => l);
}
