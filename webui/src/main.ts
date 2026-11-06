import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import TrayPanel from "./TrayPanel.svelte";
import LiveOverlay from "./LiveOverlay.svelte";
import WatchWindow from "./WatchWindow.svelte";

// "?tray": the small panel the tray icon opens (app/desktop.py), not the app.
// "?live=tiktok_1": the page for OBS, a TikTok account's LIVE answers as captions, spoken (LiveOverlay.svelte).
// "?watch=minecraft_1": a Minecraft account's view in a window of its own, HUD and controls and all.
const params = new URLSearchParams(location.search);
const page = params.has("live") ? LiveOverlay : params.has("tray") ? TrayPanel : params.has("watch") ? WatchWindow : App;
const app = mount(page, { target: document.getElementById("app")! });

export default app;
