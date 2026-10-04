/**
 * When a message was sent, as the Chats tab and Big Picture say it
 * (webui/src/lib/fmt.ts, whenSent), run for real under Node.
 */
const fmt = await import("../webui/src/lib/fmt.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const now = new Date(2026, 8, 29, 21, 30);            // Tue 29 Sep 2026, 21:30
const at = (d, h, m) => new Date(2026, 8, d, h, m).getTime() / 1000;
const time = (h, m) => fmt.fmtDate(new Date(2026, 8, 29, h, m), fmt.HOUR_MINUTE);

const today = fmt.whenSent(at(29, 14, 32), now);
check("today is just the time", today === time(14, 32), today);
const yesterday = fmt.whenSent(at(28, 23, 59), now);
check("yesterday says so, even a minute before midnight", yesterday.startsWith("Yesterday "), yesterday);
const thisWeek = fmt.whenSent(at(25, 9, 5), now);
check("this week is the weekday", /^\S+ /.test(thisWeek) && !thisWeek.startsWith("Yesterday") && !/\d+ \S+ /.test(thisWeek), thisWeek);
const older = fmt.whenSent(at(12, 9, 5), now);
check("older is the date", older.includes("12"), older);
check("nothing for no time at all", fmt.whenSent(0, now) === "");

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
