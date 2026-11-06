// The Minecraft connection through the account's own proxy (MC_PROXY). minecraft-protocol takes a `connect` that hands it
// a socket once the way is open, so this opens it: a SOCKS5 greeting, or an HTTP CONNECT. Nothing here needs a package, as
// mindcraft's node_modules have no SOCKS client to count on.
import dns from "dns";
import net from "net";

const SOCKS_ERRORS = { 1: "general failure", 2: "not allowed", 3: "network unreachable", 4: "host unreachable",
                       5: "connection refused", 6: "TTL expired", 7: "command not supported", 8: "address type not supported" };

/** host:port and the login of a proxy written the way a browser writes one. */
export function parseProxy(raw) {
  const u = new URL(String(raw).includes("://") ? String(raw) : `http://${raw}`);
  const socks = u.protocol.startsWith("socks");
  return { socks, host: u.hostname, port: Number(u.port) || (socks ? 1080 : 8080),
           user: decodeURIComponent(u.username || ""), pass: decodeURIComponent(u.password || "") };
}

/** Stop reading the greeting off a socket, leaving it paused with what came after put back. Left flowing, what was put back
 *  would sit there until the server next spoke, and on a stream whose server speaks first nothing would ever move it. */
function handOver(socket, onData, after) {
  socket.removeListener("data", onData);
  socket.pause();
  if (after.length) socket.unshift(after);
}

/** Read exactly what `steps` asks for, a step at a time, off a socket that may hand it over in any size of piece. */
function reader(socket, fail) {
  let held = Buffer.alloc(0);
  let wanted = null;
  const pump = () => {
    while (wanted && held.length >= wanted.n) {
      const { n, then } = wanted;
      const got = held.subarray(0, n);
      held = held.subarray(n);
      wanted = null;
      then(got);
    }
  };
  const onData = (d) => { held = Buffer.concat([held, d]); pump(); };
  socket.on("data", onData);
  socket.once("close", () => { if (wanted) fail(new Error("the proxy closed the connection")); });
  return {
    read(n, then) { wanted = { n, then }; pump(); },
    /** Done with the greeting: nothing more is read here, and anything already read is the server's. */
    finish() { handOver(socket, onData, held); },
  };
}

function socks5(socket, p, host, port, ready, fail) {
  const r = reader(socket, fail);
  const auth = p.user ? [0x00, 0x02] : [0x00];
  socket.write(Buffer.from([0x05, auth.length, ...auth]));
  const request = () => {
    const name = Buffer.from(host, "utf8");
    const at = Buffer.alloc(2);
    at.writeUInt16BE(port);
    socket.write(Buffer.concat([Buffer.from([0x05, 0x01, 0x00, 0x03, name.length]), name, at]));
    r.read(4, (head) => {
      if (head[1] !== 0) return fail(new Error(`the SOCKS proxy said: ${SOCKS_ERRORS[head[1]] || head[1]}`));
      const rest = (n) => r.read(n + 2, () => { r.finish(); ready(); });
      if (head[3] === 1) return rest(4);
      if (head[3] === 4) return rest(16);
      if (head[3] === 3) return r.read(1, (len) => rest(len[0]));
      return fail(new Error("the SOCKS proxy gave an address it should not have"));
    });
  };
  r.read(2, (hello) => {
    if (hello[0] !== 0x05) return fail(new Error("that is not a SOCKS5 proxy"));
    if (hello[1] === 0x00) return request();
    if (hello[1] !== 0x02 || !p.user) return fail(new Error("the SOCKS proxy wants a login it was not given"));
    const user = Buffer.from(p.user, "utf8");
    const pass = Buffer.from(p.pass, "utf8");
    socket.write(Buffer.concat([Buffer.from([0x01, user.length]), user, Buffer.from([pass.length]), pass]));
    r.read(2, (said) => {
      if (said[1] !== 0) return fail(new Error("the SOCKS proxy refused its login"));
      request();
    });
  });
}

function httpConnect(socket, p, host, port, ready, fail) {
  const login = p.user ? `Proxy-Authorization: Basic ${Buffer.from(`${p.user}:${p.pass}`).toString("base64")}\r\n` : "";
  socket.write(`CONNECT ${host}:${port} HTTP/1.1\r\nHost: ${host}:${port}\r\n${login}\r\n`);
  let held = Buffer.alloc(0);
  const onData = (d) => {
    held = Buffer.concat([held, d]);
    const end = held.indexOf("\r\n\r\n");
    if (end < 0) {
      if (held.length > 8192) { socket.removeListener("data", onData); fail(new Error("the proxy did not answer as an HTTP proxy")); }
      return;
    }
    handOver(socket, onData, held.subarray(end + 4));
    const status = /^HTTP\/\d(?:\.\d)? (\d{3})/.exec(held.subarray(0, end).toString("latin1"));
    if (!status || status[1] !== "200") return fail(new Error(`the proxy said ${status ? status[1] : "something else"}`));
    ready();
  };
  socket.on("data", onData);
}

/** Open the way to host:port through a proxy, and hand over the socket: (error, socket). It comes paused, so nothing the
 *  server has said is lost before whoever takes it is listening: piping it starts it, or call resume(). */
export function openThrough(raw, host, port, done, patience = 20000) {
  const p = parseProxy(raw);
  const socket = net.connect(p.port, p.host);
  let over = false;
  const fail = (e) => {
    if (over) return;
    over = true;
    clearTimeout(timer);
    socket.destroy();
    done(e);
  };
  const ready = () => {
    if (over) return;
    over = true;
    clearTimeout(timer);
    socket.removeListener("error", fail);
    done(null, socket);
  };
  const timer = setTimeout(() => fail(new Error("the proxy did not answer")), patience);
  socket.once("error", fail);
  socket.once("connect", () => (p.socks ? socks5 : httpConnect)(socket, p, host, port, ready, fail));
}

/** What minecraft-protocol's options.connect takes, for a bot or a ping. It looks for the server's SRV record first, as the
 *  library does when left to connect by itself, and leaves the answer in the options, which its handshake then names. */
export function connectThrough(raw, options, resolveSrv = dns.resolveSrv) {
  return (client) => {
    const go = () => openThrough(raw, options.host, options.port, (error, socket) => {
      if (error) return client.emit("error", error);
      client.setSocket(socket);
      socket.resume();
      client.emit("connect");
    });
    if (options.port !== 25565 || net.isIP(options.host) || options.host === "localhost") return go();
    resolveSrv(`_minecraft._tcp.${options.host}`, (err, found) => {
      if (!err && found?.length) {
        options.host = found[0].name;
        options.port = found[0].port;
      }
      go();
    });
  };
}

/** A bot's or a ping's options, going through the account's proxy. As they were with no proxy, or when they only go to
 *  ViaProxy on this computer: ViaProxy is then what goes through it (minecraft_runner.mjs tells it). */
export function throughProxy(options, raw = process.env.MC_PROXY) {
  const host = String(options?.host || "localhost");
  if (!raw || options?.connect || ["127.0.0.1", "localhost"].includes(host)) return options;
  const out = { ...options, host, port: Number(options.port) || 25565 };
  out.connect = connectThrough(raw, out);
  return out;
}
