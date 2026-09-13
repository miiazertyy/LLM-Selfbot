<script lang="ts">
  /**
   * Discord profile editor.
   *
   * Drives the account's own runner over the existing IPC commands, the same
   * ones the Telegram controller uses, so edits land on the real Discord
   * profile: set_status, set_bio, set_pfp, set_banner, add_friend.
   *
   * The runner has to be running for any of this to work; a stopped account
   * simply times out, which is reported as such.
   */
  import { api } from "../api";
  import { toast } from "../stores";
  import Button from "./Button.svelte";

  let { target } = $props<{ target: string | number }>();

  let emoji = $state("");
  let statusText = $state("");
  let bio = $state("");
  let pfpUrl = $state("");
  let bannerUrl = $state("");
  let friendId = $state("");
  let busy = $state("");

  /** Read a picked file as bare base64 (no data: prefix, the runner decodes raw). */
  function toBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
      r.onerror = () => reject(new Error("Could not read that file"));
      r.readAsDataURL(file);
    });
  }

  async function run(key: string, cmd: string, payload: any, okMsg: string) {
    busy = key;
    try {
      const res = await api.command(String(target), cmd, payload, 25);
      const r = res?.result ?? res;
      if (r && r.ok === false) toast(r.reason || "Discord rejected that.", "err");
      else toast(okMsg, "ok");
    } catch (e: any) {
      toast(e.message || "The account did not respond, is it running?", "err");
    } finally {
      busy = "";
    }
  }

  async function pick(key: string, cmd: string, e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      toast("That image is over 8 MB, Discord will reject it.", "err");
      input.value = "";
      return;
    }
    try {
      const b64 = await toBase64(file);
      await run(key, cmd, { b64 }, "Uploaded.");
    } catch (err: any) {
      toast(err.message, "err");
    } finally {
      input.value = "";
    }
  }
</script>

<!-- Each block is label -> field -> actions. Actions sit on their own row and
     are `self-start` so they size to their text: as direct flex children they
     would otherwise stretch to the full width and read as slabs. -->
<div class="space-y-5">
  <p class="text-[11px] leading-relaxed text-faint">
    These change the real Discord profile of this account, which must be running.
  </p>

  <section>
    <div class="mb-1.5 text-[12px] font-medium text-ink">Custom status</div>
    <div class="flex gap-2">
      <input bind:value={emoji} placeholder="🙂" aria-label="Status emoji"
             class="field w-14 shrink-0 text-center" />
      <input bind:value={statusText} placeholder="What's happening" class="field min-w-0 flex-1" />
    </div>
    <div class="mt-2 flex flex-wrap items-center gap-2">
      <Button size="sm" loading={busy === "status"}
              onclick={() => run("status", "set_status", { emoji, text: statusText }, "Status set.")}>
        Set status
      </Button>
      <Button kind="ghost" size="sm"
              onclick={() => { emoji = ""; statusText = ""; run("status", "set_status", { emoji: "", text: "" }, "Status cleared."); }}>
        Clear
      </Button>
    </div>
  </section>

  <section>
    <div class="mb-1.5 text-[12px] font-medium text-ink">About me</div>
    <textarea bind:value={bio} rows={3} maxlength={190} placeholder="Bio" class="field resize-y"></textarea>
    <div class="mt-2 flex flex-wrap items-center gap-2">
      <Button size="sm" loading={busy === "bio"}
              onclick={() => run("bio", "set_bio", { text: bio }, "Bio updated.")}>
        Save bio
      </Button>
      <span class="text-[11px] text-faint">{bio.length}/190</span>
    </div>
  </section>

  <section>
    <div class="mb-1.5 text-[12px] font-medium text-ink">Avatar</div>
    <input bind:value={pfpUrl} placeholder="https://… image URL" spellcheck="false"
           class="field font-mono text-[12px]" />
    <div class="mt-2 flex flex-wrap items-center gap-2">
      <Button size="sm" loading={busy === "pfp"} disabled={!pfpUrl.trim()}
              onclick={() => run("pfp", "set_pfp", { url: pfpUrl }, "Avatar updated.")}>
        Set from URL
      </Button>
      <label class="jelly inline-flex cursor-pointer items-center rounded-[10px] border border-edge px-2.5 py-1 text-xs font-medium text-ink hover:bg-white/[0.07]">
        Upload file
        <input type="file" accept="image/*" class="hidden" onchange={(e) => pick("pfp", "set_pfp", e)} />
      </label>
    </div>
  </section>

  <section>
    <div class="mb-1.5 text-[12px] font-medium text-ink">Banner</div>
    <input bind:value={bannerUrl} placeholder="https://… image URL" spellcheck="false"
           class="field font-mono text-[12px]" />
    <div class="mt-2 flex flex-wrap items-center gap-2">
      <Button size="sm" loading={busy === "banner"} disabled={!bannerUrl.trim()}
              onclick={() => run("banner", "set_banner", { url: bannerUrl }, "Banner updated.")}>
        Set from URL
      </Button>
      <label class="jelly inline-flex cursor-pointer items-center rounded-[10px] border border-edge px-2.5 py-1 text-xs font-medium text-ink hover:bg-white/[0.07]">
        Upload file
        <input type="file" accept="image/*" class="hidden" onchange={(e) => pick("banner", "set_banner", e)} />
      </label>
      <span class="text-[11px] text-faint">Needs Nitro</span>
    </div>
  </section>

  <section>
    <div class="mb-1.5 text-[12px] font-medium text-ink">Add friend</div>
    <input bind:value={friendId} placeholder="User ID" spellcheck="false" class="field font-mono" />
    <div class="mt-2">
      <Button size="sm" loading={busy === "friend"} disabled={!friendId.trim()}
              onclick={() => run("friend", "add_friend", { user_id: friendId }, "Friend request sent.")}>
        Send request
      </Button>
    </div>
  </section>
</div>
