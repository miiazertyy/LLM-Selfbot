<script lang="ts">
  /**
   * Signing in with GitHub, with a code: the app gets one from GitHub, you type it on GitHub's own page in your
   * browser, and that's it. No password passes through the app. The sign-in can only open requests (issues) in the
   * app's own repo and keep your own private gist.
   */
  import { onMount } from "svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import { api } from "../api";
  import { visiblePoll } from "../poll";
  import { play } from "../uisound";
  import { openGitHub } from "../window";

  let { onsignedin, compact = false }: { onsignedin?: () => void; compact?: boolean } = $props();

  type St = { state: string; user_code: string; expires_at: number; left: number; reason: string;
              me: { signed_in: boolean; login: string; avatar: string } };
  let st = $state<St | null>(null);
  let shown = $state(0);
  let copied = $state(false);
  let stopPoll: (() => void) | null = null;
  let now = $state(Date.now() / 1000);

  onMount(() => {
    api.githubSignin().then((s) => (st = s)).catch(() => {});
    const t = setInterval(() => (now = Date.now() / 1000), 1000);
    return () => {
      clearInterval(t);
      stopPoll?.();
    };
  });

  /** The code typed in, one letter after another, each with a key. */
  function typeIn(code: string) {
    shown = 0;
    [...code].forEach((_, i) => setTimeout(() => {
      shown = i + 1;
      play("key", { level: 0.35, p: 0.3 + (0.5 * i) / Math.max(1, code.length - 1) });
    }, 120 + i * 45));
  }

  function poll() {
    stopPoll?.();
    stopPoll = visiblePoll(async () => {
      const s: St = await api.githubSignin();
      const was = st?.state;
      st = s;
      if (s.state === "waiting") return;
      stopPoll?.();
      stopPoll = null;
      if (s.state === "done" && was !== "done") {
        play("done");
        play("glint", { delay: 160, strong: true });
        onsignedin?.();
      } else if (["failed", "expired", "denied"].includes(s.state)) {
        play("err", { level: 0.6 });
      }
    }, 1500);
  }

  async function start() {
    play("tap");
    try {
      st = await api.githubSigninStart();
    } catch (e: any) {
      st = { ...(st as St), state: "failed", reason: e?.message || "It couldn't start." };
      play("err", { level: 0.6 });
      return;
    }
    if (st?.state === "waiting") {
      typeIn(st.user_code);
      poll();
    } else if (st?.state === "failed") {
      play("err", { level: 0.6 });
    }
  }

  async function copy() {
    if (!st?.user_code) return;
    play("select");
    try {
      await navigator.clipboard.writeText(st.user_code);
      copied = true;
      play("ok", { delay: 120, level: 0.5 });
      setTimeout(() => (copied = false), 1600);
    } catch {
      /* the code is on screen to type */
    }
  }

  function goToGitHub() {
    play("open");
    copy();
    openGitHub("device");
  }

  async function cancel() {
    play("off");
    stopPoll?.();
    st = await api.githubSigninCancel();
  }

  async function signOut() {
    play("off");
    st = await api.githubSignout();
  }

  const left = $derived(st && st.state === "waiting" ? Math.max(0, Math.round(st.expires_at - now)) : 0);
  const frac = $derived(st && st.state === "waiting" ? Math.min(1, left / 900) : 0);
</script>

<div class="si" class:is-compact={compact}>
  {#if !st}
    <span class="si-wait">Checking</span>
  {:else if st.me.signed_in}
    <div class="si-in">
      {#if st.me.avatar}<img src={st.me.avatar} alt="" />{:else}<Icon name="github" size={16} />{/if}
      <span>Signed in to GitHub as <b>{st.me.login}</b></span>
      <button type="button" class="si-out" data-sound="self" onclick={signOut}>Sign out</button>
    </div>
  {:else if st.state === "waiting"}
    <div class="si-code-box">
      <p class="si-say">Enter this code on GitHub</p>
      <div class="si-code" aria-label="Your code: {st.user_code}">
        {#each [...st.user_code] as ch, i (i)}
          <span class="si-ch" class:is-on={i < shown} class:is-dash={ch === "-"}>{ch}</span>
        {/each}
      </div>
      <div class="si-row">
        <Button size="sm" onclick={goToGitHub}><Icon name="github" size={13} />Open GitHub</Button>
        <Button size="sm" kind="ghost" onclick={copy}><Icon name={copied ? "check" : "copy"} size={12} />{copied ? "Copied" : "Copy"}</Button>
        <span class="si-ring" style="--f: {frac}" title="{Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')} left"></span>
        <button type="button" class="si-out" data-sound="self" onclick={cancel}>Cancel</button>
      </div>
      <p class="si-note">Waiting for you on GitHub. It only lets this app post requests to LLMSelfbot's repo and keep your own private gist.</p>
    </div>
  {:else}
    <div class="si-start">
      {#if st.reason}<p class="si-bad"><Icon name="alert" size={12} />{st.reason}</p>{/if}
      <Button onclick={start}><Icon name="github" size={14} />Sign in with GitHub</Button>
      {#if !compact}<p class="si-note">No password here: you get a code to enter on GitHub, in your browser.</p>{/if}
    </div>
  {/if}
</div>

<style>
  .si { display: flex; flex-direction: column; gap: 8px; }
  .si-wait { font-size: 12.5px; color: var(--color-faint); }
  .si-in { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 14px; font-size: 12.5px;
           color: var(--color-muted); background: color-mix(in srgb, var(--color-good) 8%, transparent);
           box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 28%, transparent); }
  .si-in img { width: 22px; height: 22px; border-radius: 999px; }
  .si-in b { color: var(--color-ink); }
  .si-out { margin-left: auto; padding: 4px 9px; border-radius: 8px; font-size: 11.5px; color: var(--color-faint);
            transition: background-color 0.15s ease, color 0.15s ease; }
  .si-out:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .si-code-box { display: flex; flex-direction: column; gap: 10px; padding: 14px; border-radius: 16px;
                 background: radial-gradient(120% 120% at 0% 0%, color-mix(in srgb, var(--color-accent) 16%, transparent), transparent 60%),
                             rgb(255 255 255 / 0.02);
                 box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, var(--color-edge)); }
  .si-say { margin: 0; font-size: 12px; font-weight: 600; color: var(--color-muted); }
  .si-code { display: flex; gap: 6px; }
  .si-ch { display: grid; width: 32px; height: 40px; place-items: center; border-radius: 10px;
           font: 700 20px/1 ui-monospace, Consolas, monospace; color: var(--color-ink);
           background: rgb(0 0 0 / 0.28); box-shadow: inset 0 0 0 1px var(--color-edge);
           opacity: 0; transform: translateY(6px) scale(0.9); transition: opacity 0.2s ease, transform 0.3s var(--spring); }
  .si-ch.is-on { opacity: 1; transform: none; }
  .si-ch.is-dash { width: 14px; background: none; box-shadow: none; color: var(--color-faint); }
  .si-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .si-ring { width: 18px; height: 18px; border-radius: 999px;
             background: conic-gradient(var(--color-accent) calc(var(--f) * 360deg), rgb(255 255 255 / 0.08) 0);
             -webkit-mask: radial-gradient(circle, transparent 5px, #000 6px); mask: radial-gradient(circle, transparent 5px, #000 6px); }
  .si-note { margin: 0; font-size: 11.5px; line-height: 1.5; color: var(--color-faint); }
  .si-start { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
  .si-bad { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 12px; color: var(--color-bad); }
  :global(:root[data-motion="off"]) .si-ch { transition: none; opacity: 1; transform: none; }
  :global(:root[data-motion="off"]) .si-out { transition: none; }
</style>
