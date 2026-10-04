import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import TrayPanel from "./TrayPanel.svelte";

// "?tray": the small panel the tray icon opens (app/desktop.py), not the app.
const tray = new URLSearchParams(location.search).has("tray");
const app = mount(tray ? TrayPanel : App, { target: document.getElementById("app")! });

export default app;
