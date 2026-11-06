// The Minecraft connection through a proxy (app/platforms/minecraft/proxy_connect.mjs), against small proxies made here: a
// SOCKS5 with and without a login, an HTTP CONNECT, and ones that refuse. Nothing leaves this computer. Run by
// tests/test_proxies.py. Ends with process.exitCode, as a plain exit after these imports aborts on this Node.
import net from "net";
import { connectThrough, openThrough, parseProxy, throughProxy } from "../app/platforms/minecraft/proxy_connect.mjs";

let passed = 0;
let failed = 0;
const check = (name, ok, extra = "") => {
  if (ok) passed += 1; else failed += 1;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${extra && !ok ? `  [${extra}]` : ""}`);
};

/** A server that says who it is, then echoes. What comes through a proxy has to reach this. */
const target = net.createServer((s) => {
  s.write("SERVER:");
  s.on("data", (d) => s.write(d));
  s.on("error", () => {});
});
await new Promise((r) => target.listen(0, "127.0.0.1", r));
const targetPort = target.address().port;

function collect(socket, n, read = (b) => b) {
  return new Promise((resolve, reject) => {
    let held = Buffer.alloc(0);
    const on = (d) => {
      held = Buffer.concat([held, d]);
      if (held.length >= n) { socket.removeListener("data", on); resolve(read(held)); }
    };
    socket.on("data", on);
    socket.once("error", reject);
  });
}

/** What comes in on a socket, taken a piece at a time and none of it lost while nobody is asking. */
function taker(socket) {
  let held = Buffer.alloc(0);
  let wanted = null;
  const pump = () => {
    if (!wanted || held.length < wanted.n) return;
    const { n, resolve } = wanted;
    wanted = null;
    const got = held.subarray(0, n);
    held = held.subarray(n);
    resolve(got);
  };
  const on = (d) => { held = Buffer.concat([held, d]); pump(); };
  socket.on("data", on);
  return {
    take: (n) => new Promise((resolve) => { wanted = { n, resolve }; pump(); }),
    stop() {
      socket.removeListener("data", on);
      socket.pause();
      if (held.length) socket.unshift(held);
    },
  };
}

/** A SOCKS5 that takes what it is told to: optionally wanting a login, optionally refusing the connection. Sends its answers
 *  a byte at a time when asked to, which is how they may come. */
function socksProxy({ login = null, refuse = 0, slow = false } = {}) {
  const seen = { greeted: 0, user: "", pass: "", host: "", port: 0 };
  const server = net.createServer((client) => {
    client.on("error", () => {});
    const say = async (buf) => {
      if (!slow) return client.write(buf);
      for (const b of buf) {
        client.write(Buffer.from([b]));
        await new Promise((r) => setTimeout(r, 2));
      }
    };
    const from = taker(client);
    (async () => {
      const hello = await from.take(2);
      await from.take(hello[1]);
      seen.greeted += 1;
      if (login) {
        await say(Buffer.from([0x05, 0x02]));
        const head = await from.take(2);
        seen.user = (await from.take(head[1])).toString();
        const plen = (await from.take(1))[0];
        seen.pass = (await from.take(plen)).toString();
        const good = seen.user === login.user && seen.pass === login.pass;
        await say(Buffer.from([0x01, good ? 0 : 1]));
        if (!good) return client.end();
      } else {
        await say(Buffer.from([0x05, 0x00]));
      }
      const req = await from.take(5);
      seen.host = (await from.take(req[4])).toString();
      seen.port = (await from.take(2)).readUInt16BE(0);
      if (refuse) {
        await say(Buffer.from([0x05, refuse, 0x00, 0x01, 0, 0, 0, 0, 0, 0]));
        return client.end();
      }
      const up = net.connect(targetPort, "127.0.0.1");
      up.on("error", () => client.destroy());
      await new Promise((r) => up.once("connect", r));
      await say(Buffer.from([0x05, 0x00, 0x00, 0x01, 127, 0, 0, 1, 0, 80]));
      from.stop();
      client.pipe(up);
      up.pipe(client);
    })().catch(() => client.destroy());
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r({ server, seen, port: server.address().port })));
}

/** An HTTP proxy that takes CONNECT, saying nothing else at first, or a status it is told to. */
function httpProxy({ status = 200, wantLogin = "" } = {}) {
  const seen = { first: "", login: "" };
  const server = net.createServer((client) => {
    client.on("error", () => {});
    let held = "";
    const on = (d) => {
      held += d.toString("latin1");
      if (!held.includes("\r\n\r\n")) return;
      client.removeListener("data", on);
      seen.first = held.split("\r\n")[0];
      seen.login = /Proxy-Authorization: (.+)\r\n/.exec(held)?.[1] || "";
      if (status !== 200 || (wantLogin && seen.login !== wantLogin)) {
        client.end(`HTTP/1.1 ${status === 200 ? 407 : status} No\r\n\r\n`);
        return;
      }
      const up = net.connect(targetPort, "127.0.0.1");
      up.on("error", () => client.destroy());
      up.once("connect", () => {
        client.write("HTTP/1.1 200 Connection established\r\n\r\n");
        client.pipe(up);
        up.pipe(client);
      });
    };
    client.on("data", on);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r({ server, seen, port: server.address().port })));
}

const through = (url, host = "mc.example.net", port = 25565) => new Promise((resolve) => {
  openThrough(url, host, port, (error, socket) => resolve({ error, socket }));
});

async function talks(socket) {
  const heard = collect(socket, 7, (b) => b.toString());
  socket.resume();
  const first = await heard;
  socket.write("hello");
  const second = await collect(socket, 5, (b) => b.toString());
  socket.destroy();
  return first === "SERVER:" && second === "hello";
}

// What a proxy looks like.
let p = parseProxy("socks5://me:se%40cret@1.2.3.4:1080");
check("a SOCKS proxy read, its password undone", p.socks && p.host === "1.2.3.4" && p.port === 1080 && p.user === "me" && p.pass === "se@cret");
p = parseProxy("1.2.3.4:8080");
check("nothing said: an http one", !p.socks && p.port === 8080);

// SOCKS5.
{
  const px = await socksProxy();
  const { error, socket } = await through(`socks5://127.0.0.1:${px.port}`);
  check("through SOCKS5, with no login", !error && socket, String(error));
  check("asked for the server by name, so the proxy looks it up", px.seen.host === "mc.example.net" && px.seen.port === 25565, JSON.stringify(px.seen));
  check("and it talks both ways, the server's first words too", await talks(socket));
  px.server.close();
}
{
  const px = await socksProxy({ slow: true });
  const { error, socket } = await through(`socks5://127.0.0.1:${px.port}`);
  check("its answers coming a byte at a time make no difference", !error && (await talks(socket)), String(error));
  px.server.close();
}
{
  const px = await socksProxy({ login: { user: "me", pass: "pw" } });
  const { error, socket } = await through(`socks5://me:pw@127.0.0.1:${px.port}`);
  check("with a login", !error && px.seen.user === "me" && px.seen.pass === "pw" && (await talks(socket)), String(error));
  const wrong = await through(`socks5://me:nope@127.0.0.1:${px.port}`);
  check("a wrong one says so", /refused its login/.test(String(wrong.error?.message)), String(wrong.error));
  const none = await through(`socks5://127.0.0.1:${px.port}`);
  check("and none at all, when it wants one, says that", /wants a login/.test(String(none.error?.message)), String(none.error));
  px.server.close();
}
{
  const px = await socksProxy({ refuse: 5 });
  const { error } = await through(`socks5://127.0.0.1:${px.port}`);
  check("a server it cannot reach is said in words", /connection refused/.test(String(error?.message)), String(error));
  px.server.close();
}

// HTTP CONNECT.
{
  const px = await httpProxy();
  const { error, socket } = await through(`http://127.0.0.1:${px.port}`);
  check("through an http proxy", !error && px.seen.first === "CONNECT mc.example.net:25565 HTTP/1.1" && (await talks(socket)), `${error} ${px.seen.first}`);
  px.server.close();
}
{
  const want = `Basic ${Buffer.from("me:pw").toString("base64")}`;
  const px = await httpProxy({ wantLogin: want });
  const { error, socket } = await through(`http://me:pw@127.0.0.1:${px.port}`);
  check("with a login", !error && px.seen.login === want && (await talks(socket)), String(error));
  const wrong = await through(`http://127.0.0.1:${px.port}`);
  check("refused, it says what it was told", /407/.test(String(wrong.error?.message)), String(wrong.error));
  px.server.close();
}

// Nothing there.
{
  const unused = net.createServer();
  await new Promise((r) => unused.listen(0, "127.0.0.1", r));
  const port = unused.address().port;
  await new Promise((r) => unused.close(r));
  const { error } = await through(`socks5://127.0.0.1:${port}`);
  check("no proxy where it says: an error, not a hang", !!error, "no error");
}

{
  const silent = net.createServer((s) => s.on("error", () => {}));
  await new Promise((r) => silent.listen(0, "127.0.0.1", r));
  const error = await new Promise((resolve) => {
    openThrough(`socks5://127.0.0.1:${silent.address().port}`, "mc.example.net", 25565, (e) => resolve(e), 150);
  });
  check("one that takes the connection and says nothing is given up on", /did not answer/.test(String(error?.message)), String(error));
  silent.close();
}

// As minecraft-protocol uses it.
{
  const px = await socksProxy();
  const events = [];
  const client = {
    setSocket(s) { events.push("socket"); this.socket = s; },
    emit(name, value) { events.push(name); if (name === "connect") this.done?.(); if (name === "error") this.failed = value; },
  };
  await new Promise((resolve) => { client.done = resolve; connectThrough(`socks5://127.0.0.1:${px.port}`, { host: "mc.example.net", port: 25570 })(client); });
  check("handed to the client, then told it is connected", events.join(",") === "socket,connect", events.join(","));
  check("on the port of the server", px.seen.port === 25570);
  client.socket.destroy();
  px.server.close();
}

// A server's SRV record, as the library looks one up when left to itself. Stood in for here, so nothing leaves this computer.
async function joinWith(options, resolver) {
  const px = await socksProxy();
  let looked = "";
  const lookup = (name, then) => { looked = name; resolver(then); };
  const client = { setSocket(s) { this.socket = s; }, emit() { this.done?.(); } };
  await new Promise((resolve) => { client.done = resolve; connectThrough(`socks5://127.0.0.1:${px.port}`, options, lookup)(client); });
  client.socket.destroy();
  px.server.close();
  return { looked, host: px.seen.host, port: px.seen.port };
}
{
  const options = { host: "play.example.net", port: 25565 };
  const r = await joinWith(options, (then) => then(null, [{ name: "node7.example.net", port: 25601 }]));
  check("the default port looks for one", r.looked === "_minecraft._tcp.play.example.net", r.looked);
  check("and goes where it says", r.host === "node7.example.net" && r.port === 25601, JSON.stringify(r));
  check("leaving that in the options, which the handshake names", options.host === "node7.example.net" && options.port === 25601);
  const none = await joinWith({ host: "play.example.net", port: 25565 }, (then) => then(new Error("ENOTFOUND")));
  check("none found: the name as it was typed", none.host === "play.example.net" && none.port === 25565, JSON.stringify(none));
  const other = await joinWith({ host: "play.example.net", port: 25570 }, () => { throw new Error("asked"); });
  check("another port was chosen on purpose: not looked for", other.looked === "" && other.port === 25570, JSON.stringify(other));
  const ip = await joinWith({ host: "1.2.3.4", port: 25565 }, () => { throw new Error("asked"); });
  check("nor for an address", ip.looked === "" && ip.host === "1.2.3.4", JSON.stringify(ip));
}

// What wraps a bot and a ping.
{
  const given = { host: "play.example.net", port: "25566", username: "someone" };
  const out = throughProxy(given, "socks5://1.2.3.4:1080");
  check("a bot goes through it", typeof out.connect === "function" && out.username === "someone" && out.port === 25566);
  check("what it was given stays as it was", !("connect" in given));
  const blank = throughProxy({ host: "play.example.net" }, "socks5://1.2.3.4:1080");
  check("no port said: the default", blank.port === 25565);
  const plain = { host: "play.example.net", port: 25565 };
  check("no proxy: nothing changes", throughProxy(plain, "") === plain);
  const local = { host: "127.0.0.1", port: 25599 };
  check("to ViaProxy on this computer: nothing changes, ViaProxy is what goes through it", throughProxy(local, "socks5://1.2.3.4:1080") === local);
  const named = { host: "localhost", port: 25599 };
  check("by name too", throughProxy(named, "socks5://1.2.3.4:1080") === named);
  const none = {};
  check("no host at all means this computer", throughProxy(none, "socks5://1.2.3.4:1080") === none);
  const own = { host: "play.example.net", connect() {} };
  check("nor over a connection someone already chose", throughProxy(own, "socks5://1.2.3.4:1080") === own);
}

target.close();
console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
