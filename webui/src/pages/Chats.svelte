<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { toast } from "../lib/stores";
  import { resource } from "../lib/resource";
  import {
    chatAccounts, chatCache, loadChatAccounts, refreshChats,
    replying as replyingStore, replyingAll as replyingAllStore, sendReply, sendReplyAll,
    replyAllProgress,
  } from "../lib/chats";
  import Card from "../lib/components/Card.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Empty from "../lib/components/Empty.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import UserChip from "../lib/components/UserChip.svelte";
  import Avatar from "../lib/components/Avatar.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";

  type ChatUser = {
    id: string; name: string; snippet: string; count: number; ts?: number;
    /** Unix seconds when the bot will answer this on its own. */
    reply_at?: number | null;
    /** Filled in by the server from the local profile cache; may be empty. */
    avatar?: string;
    username?: string;
  };
  type Account = {
    id: string;
    platform: string;
    account: number | null;
    username?: string;
    display_name?: string;
    avatar?: string;
    state?: string;
  };

  let target = $state("");
  let loadError = $state("");

  // One clock for every countdown on the page: a friend request that is due in
  // four minutes, and a reply held back by the cooldown.
  let now = $state(Date.now() / 1000);

  // Friend requests waiting on this account. The background loop accepts them
  // over hours on purpose, to not look like a script; this is for when you are
  // watching one arrive and just want it in.
  type FriendRequest = {
    id: string;
    username: string;
    display_name?: string;
    avatar?: string;
    incoming: boolean;
    /** Unix seconds when the bot will accept it on its own, if scheduled. */
    accept_at?: number | null;
  };
  let requests = $state<FriendRequest[]>([]);
  let friendsSupported = $state(true);
  let friendBusy = $state<Record<string, boolean>>({});
  // Why the list is empty, when it is empty for a reason. Swallowing this made
  // a failure and "no requests" look exactly the same.
  let friendsError = $state("");
  let friendsLoaded = $state(false);
  // Asking the account for its friend requests is an IPC round trip, so the
  // answer arrives after the page does. Saying so means an empty page reads as
  // "still looking" rather than "nobody has added you".
  let friendsLoading = $state(false);

  // Everyone already dealt with. Cached like the rest of the page, and folded
  // away by default: the waiting list is the job, this is the history.
  type Past = {
    id: string; name: string; username?: string; avatar?: string;
    messages: number; last_ts?: number;
  };
  const past = resource("chatArchive", () => api.chatArchive(40),
                        { conversations: [] as Past[] });
  let showPast = $state(false);

  /** Anyone still waiting is on the list above, so they are not history yet. */
  const archived = $derived(
    ($past.data.conversations ?? []).filter((c) => !users.some((u) => u.id === c.id)),
  );

  const incoming = $derived(requests.filter((r) => r.incoming));

  // Held in the store, so a reply that takes two minutes is still shown as
  // running when you leave the tab and come back.
  const replying = $derived($replyingStore);
  const replyingAll = $derived(!!$replyingAllStore[target]);
  const allProgress = $derived($replyAllProgress[target]);

  // Anything in flight blocks the other send buttons.
  const busy = $derived(replyingAll || Object.keys(replying).length > 0);

  // The conversations live in a module store that outlives this page, filled
  // by a background pass from app start. Opening the tab therefore renders
  // whatever was last known, immediately, instead of a skeleton.
  const accounts = $derived($chatAccounts);
  const entry = $derived($chatCache[target] ?? { users: [], fetched: 0, loading: false, error: "" });
  const users = $derived(entry.users);

  /** Only blank on a genuinely cold start, never on a refresh. */
  const loading = $derived(!accounts.length || (!entry.fetched && entry.loading));
  const refreshing = $derived(entry.loading && entry.fetched > 0);

  /**
   * Oldest first.
   *
   * A conversation from yesterday that never got answered is the one worth
   * seeing; one that arrived a minute ago will be handled on its own. A ts of 0
   * means it arrived this session, so it sorts last.
   */
  const ordered = $derived(
    [...users].sort((a, b) => (a.ts || Infinity) - (b.ts || Infinity)),
  );

  const waitingLongest = $derived(ordered.filter((u) => stale(u.ts)).length);

  const current = $derived(accounts.find((a) => a.id === target));
  const unread = $derived(users.reduce((n, u) => n + (u.count || 0), 0));

  onMount(() => {
    void start();
    const clock = setInterval(() => (now = Date.now() / 1000), 1000);
    // The page refreshes the account you are looking at more often than the
    // background pass does, since that one is there to keep the tab instant
    // rather than to be the freshest source.
    const t = setInterval(() => {
      refreshChats(target, { maxAge: 10000 });
      loadFriends();
    }, 15000);
    return () => {
      clearInterval(t);
      clearInterval(clock);
    };
  });

  async function start() {
    try {
      const list = accounts.length ? accounts : await loadChatAccounts();
      if (list.length && !target) target = list[0].id;
      // Both at once. Awaiting the conversation sweep first meant friend
      // requests waited behind an IPC round trip that can take ten seconds,
      // so they appeared long after the rest of the page.
      await Promise.all([
        refreshChats(target, { maxAge: 10000 }),
        loadFriends(),
        past.refresh({ maxAge: 30000 }),
      ]);
    } catch (e: any) {
      loadError = e?.message || "Could not load";
    }
  }

  async function loadFriends() {
    if (!target) return;
    friendsLoading = true;
    try {
      const data = await api.friends(target);
      requests = data.requests || [];
      friendsSupported = data.supported !== false;
      friendsError = "";
    } catch (e: any) {
      // Keep whatever is already listed: a failed refresh should not make a
      // request you can see disappear. And say what went wrong, because an
      // empty list and a broken one used to look identical.
      friendsError = e?.status === 504
        ? "The account did not answer. It may be stopped or busy."
        : e?.message || "Could not read friend requests";
    } finally {
      friendsLoading = false;
      friendsLoaded = true;
    }
  }

  async function answerRequest(r: FriendRequest, action: "accept" | "decline") {
    friendBusy[r.id] = true;
    try {
      const res = await api.friendAction(action, r.id, target);
      if (res?.ok) {
        requests = requests.filter((x) => x.id !== r.id);
        toast(
          `${action === "accept" ? "Accepted" : "Declined"} ${r.display_name || r.username}.`,
          "ok",
        );
      } else {
        toast(res?.reason || "Discord refused that", "err");
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
    friendBusy[r.id] = false;
  }

  /**
   * The two halves of an account's identity, kept apart.
   *
   * They used to be joined into one string for a native select option, because
   * that is all an option can hold. "Discord #1 · ! Alicia" put the least
   * interesting half first and made the name look like a suffix. Now the name
   * leads and the slot is a quiet pill beside it.
   */
  function who(a: Account): string {
    return a.display_name || a.username || slot(a);
  }

  function slot(a: Account): string {
    const platform = a.platform === "discord" ? "Discord" : "Snapchat";
    return `${platform}${a.account ? ` #${a.account}` : ""}`;
  }

  /**
   * Whether the slot is worth showing next to the name.
   *
   * An account that has never connected has no name to fall back from, so
   * `who` returns the slot itself. Printing the pill then gives you
   * "Discord #1" twice on one line.
   */
  function named(a: Account): boolean {
    return who(a) !== slot(a);
  }

  /** Only worth opening a picker when there is something to pick. */
  const multiple = $derived(accounts.length > 1);

  let picking = $state(false);

  function choose(id: string) {
    picking = false;
    if (id !== target) switchTarget(id);
  }

  /**
   * The menu is absolutely positioned inside its own relative wrapper rather
   * than fixed: an ancestor with a transform (the page enter animation has
   * one) becomes the containing block for fixed elements, which is what threw
   * an earlier popover off screen entirely.
   */
  function dismiss(event: MouseEvent) {
    if (!picking) return;
    const el = event.target as HTMLElement;
    if (!el.closest?.("[data-account-picker]")) picking = false;
  }

  async function reply(u: ChatUser) {
    if (busy) return;
    try {
      const res = await sendReply(target, u.id);
      if (res && res.success === false) {
        // A conversation that can never be answered is taken off the waiting
        // list by the runner, so it stops coming back on every sweep.
        toast(
          res.dropped
            ? `${u.name}: ${res.reason}. Removed from the list.`
            : `${u.name}: ${res.reason}`,
          "err",
        );
      } else if (res) {
        toast(`Replied to ${u.name}`, "ok");
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function replyAll() {
    // While it is running the same button stops it, so `busy` must not block.
    if (replyingAll) {
      void sendReplyAll(target);           // flips the flag, the loop notices
      toast("Stopping after the reply in flight.", "info");
      return;
    }
    if (busy) return;
    try {
      const res = await sendReplyAll(target);
      if (!res) return;
      const n = res?.total ?? users.length;
      const failed = (res?.results || []).filter((r: any) => !r.success).length;
      toast(
        failed
          ? `Replied to ${n - failed} of ${n}. ${failed} could not be answered.`
          : `Replied to ${n} ${n === 1 ? "person" : "people"}`,
        failed ? "info" : "ok",
      );
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function switchTarget(id: string) {
    target = id;
    loadFriends();
    // Cached accounts appear at once. Only one that has never been fetched
    // shows a wait, and even that is usually already warm.
    await refreshChats(id, { maxAge: 10000 });
  }

  /** "in 4m 20s". Empty once the moment has passed. */
  function countdown(at?: number): string {
    if (!at) return "";
    const left = Math.max(0, Math.round(at - now));
    if (left <= 0) return "";
    if (left < 60) return `in ${left}s`;
    const m = Math.floor(left / 60);
    if (m < 60) return `in ${m}m ${left % 60}s`;
    const h = Math.floor(m / 60);
    return `in ${h}h ${m % 60}m`;
  }

  /** The clock time it will happen, for anything more than a few minutes off. */
  function at(ts?: number): string {
    if (!ts) return "";
    return new Date(ts * 1000).toLocaleTimeString(undefined,
      { hour: "2-digit", minute: "2-digit" });
  }

  const cooling = $derived(
    entry.cooldownUntil && entry.cooldownUntil > now ? entry.cooldownUntil : 0,
  );

  /** Arrived before this session, so it went unanswered while the bot was off. */
  const stale = (ts?: number) => !!ts && now - ts > 3600;

  /** "3h ago". A ts of 0 means it arrived during this session. */
  function ago(ts?: number): string {
    if (!ts) return "just now";
    const secs = Math.max(0, Date.now() / 1000 - ts);
    if (secs < 90) return "just now";
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }

  /** Older than this session means it arrived while the bot was off. */
  const offline = (ts?: number) => !!ts && Date.now() / 1000 - ts > 3600;
</script>

<ErrorNote text={loadError} onretry={() => { loadError = ""; start(); }} />

<svelte:window onclick={dismiss} onkeydown={(e) => e.key === "Escape" && (picking = false)} />

<!-- Which account you are answering as. The name leads, because that is what
     you recognise; the slot is there to tell two accounts apart. -->
<div class="mb-4 flex flex-wrap items-center gap-3">
  <!-- w-full below sm: sharing the row with the Reply to all button left
       roughly 120px for the picker, which clipped the caption under it. -->
  <div class="relative w-full min-w-0 sm:w-auto sm:flex-1" data-account-picker>
    <svelte:element
      this={multiple ? "button" : "div"}
      role={multiple ? "button" : undefined}
      aria-haspopup={multiple ? "listbox" : undefined}
      aria-expanded={multiple ? picking : undefined}
      onclick={multiple ? () => (picking = !picking) : undefined}
      class="flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-left transition-colors
        {multiple ? 'hover:bg-white/[0.04]' : ''} {picking ? 'bg-white/[0.05]' : ''}"
    >
      {#if current?.avatar}
        <img src={current.avatar} alt="" class="h-9 w-9 shrink-0 rounded-full object-cover ring-1 ring-edge" />
      {:else}
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-accent">
          <Icon name={current?.platform === "snapchat" ? "snapchat" : "accounts"} size={17} />
        </span>
      {/if}

      <span class="min-w-0 flex-1">
        <span class="flex min-w-0 items-center gap-2">
          <span class="truncate text-[14px] font-medium text-ink">
            {current ? who(current) : "No account"}
          </span>
          {#if current && named(current)}
            <span class="shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-faint">
              {slot(current)}
            </span>
          {/if}
        </span>
        <span class="mt-0.5 flex items-center gap-1.5 truncate text-[11px] text-faint">
          <span class="truncate">
            {users.length} conversation{users.length === 1 ? "" : "s"} waiting
            {#if unread}&middot; {unread} unread message{unread === 1 ? "" : "s"}{/if}
            {#if waitingLongest}
              &middot; <span class="text-warn">{waitingLongest} from before this session</span>
            {/if}
          </span>
          <!-- A refresh over cached data is a hint, not a wall: the list you
               are reading stays put while the newer answer is on its way. -->
          {#if refreshing}
            <span class="shrink-0 animate-pulse text-accent/70">checking</span>
          {/if}
        </span>
      </span>

      {#if multiple}
        <span class="shrink-0 text-faint transition-transform duration-200"
              style="transform: rotate({picking ? 180 : 0}deg)">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M2.5 4.5 6 8l3.5-3.5" stroke="currentColor" stroke-width="1.4"
                  stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
      {/if}
    </svelte:element>

    {#if picking}
      <div
        role="listbox"
        aria-label="Account to answer as"
        class="glass floating absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-xl p-1 shadow-xl"
      >
        {#each accounts as a (a.id)}
          <button
            role="option"
            aria-selected={a.id === target}
            onclick={() => choose(a.id)}
            class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors
              {a.id === target ? 'bg-accent/10' : 'hover:bg-white/[0.05]'}"
          >
            {#if a.avatar}
              <img src={a.avatar} alt="" class="h-8 w-8 shrink-0 rounded-full object-cover ring-1 ring-edge" />
            {:else}
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-accent">
                <Icon name={a.platform === "snapchat" ? "snapchat" : "accounts"} size={15} />
              </span>
            {/if}
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[13px] text-ink">{who(a)}</span>
              {#if named(a)}
                <!-- The separator lives inside the expression: Svelte trims
                     leading whitespace in a block, which glued the dot to the
                     slot as "Discord #1· @alicia.k". -->
                <span class="block truncate text-[11px] text-faint">
                  {slot(a)}{a.username && a.username !== who(a) ? ` · @${a.username}` : ""}
                </span>
              {:else}
                <span class="block truncate text-[11px] text-faint">never connected</span>
              {/if}
            </span>
            {#if a.state && a.state !== "running"}
              <span class="shrink-0"><Badge tone="muted">{a.state}</Badge></span>
            {/if}
            {#if a.id === target}
              <span class="shrink-0 text-accent"><Icon name="check" size={14} /></span>
            {/if}
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Says where it has got to, and stops. A run is minutes long - every reply
       waits out the human pause before it sends - and with one spinner and no
       numbers there was nothing to tell it apart from a hang. -->
  <Button kind={replyingAll ? "ghost" : "good"} onclick={replyAll}
          disabled={!replyingAll && (users.length === 0 || busy)}>
    {#if replyingAll && allProgress}
      Stop ({allProgress.done}/{allProgress.total})
    {:else if replyingAll}
      Stop
    {:else}
      Reply to all ({users.length})
    {/if}
  </Button>
</div>

{#if friendsLoading && !incoming.length && friendsSupported}
  <!-- Only when there is nothing listed yet: once requests are on screen a
       refresh should not push a placeholder above them. -->
  <div class="glass mb-4 flex items-center gap-3 rounded-xl px-4 py-2.5">
    <span class="shrink-0 animate-pulse text-accent"><Icon name="refresh" size={14} /></span>
    <span class="min-w-0 flex-1 text-[12px] text-muted">
      Checking for friend requests, asking the account now.
    </span>
  </div>
{/if}

{#if friendsError && friendsSupported}
  <div class="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-warn/30 bg-warn/[0.06] px-4 py-2.5">
    <span class="shrink-0 text-warn"><Icon name="alert" size={14} /></span>
    <span class="min-w-0 flex-1 text-[12px] text-warn">
      Friend requests: {friendsError}
    </span>
    <button class="shrink-0 text-[11px] text-faint hover:text-ink" onclick={loadFriends}>
      Try again
    </button>
  </div>
{/if}

{#if incoming.length}
  <!-- Above the conversations because a request is the thing that has been
       waiting longest, and answering it takes one click. -->
  <div class="glass mb-4 rounded-xl p-3">
    <div class="mb-2 flex items-baseline justify-between gap-3">
      <span class="flex items-center gap-2 text-[12px] font-medium text-ink">
        {incoming.length} friend request{incoming.length === 1 ? "" : "s"}
        {#if friendsLoading}
          <span class="animate-pulse text-[11px] font-normal text-accent/70">checking</span>
        {/if}
      </span>
      <span class="text-[11px] text-faint">
        The bot spreads accepts over hours so it does not look scripted.
        Accepting here takes one now.
      </span>
    </div>
    <div class="space-y-1.5">
      {#each incoming as r (r.id)}
        <div class="flex items-center gap-3 rounded-lg bg-white/[0.04] px-2.5 py-2">
          <Avatar src={r.avatar} name={r.display_name || r.username} size={32} />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[13px] text-ink">
              {r.display_name || r.username}
            </span>
            <span class="block truncate text-[11px] text-faint">
              {#if r.username && r.username !== (r.display_name || r.username)}@{r.username} &middot; {/if}
              {#if r.accept_at && countdown(r.accept_at)}
                <span class="text-accent/80">accepts {countdown(r.accept_at)}</span>
                <span class="text-faint">, at {at(r.accept_at)}</span>
              {:else if r.accept_at}
                accepting now
              {:else}
                waiting for you, no automatic accept scheduled
              {/if}
            </span>
          </span>
          <div class="flex shrink-0 gap-1.5">
            <Button size="sm" kind="good" loading={friendBusy[r.id]}
                    onclick={() => answerRequest(r, "accept")}>Accept</Button>
            <Button size="sm" kind="ghost" disabled={friendBusy[r.id]}
                    onclick={() => answerRequest(r, "decline")}>Decline</Button>
          </div>
        </div>
      {/each}
    </div>
  </div>
{/if}


{#if entry.paused || cooling}
  <!-- The two reasons a waiting conversation is not being answered right now.
       Without this the list just sits there looking stuck. -->
  <div class="glass mb-4 flex flex-wrap items-center gap-3 rounded-xl px-4 py-2.5">
    <span class="shrink-0 text-{entry.paused ? 'warn' : 'accent'}">
      <Icon name={entry.paused ? "pause" : "refresh"} size={14} />
    </span>
    <span class="min-w-0 flex-1 text-[12px] text-ink">
      {#if entry.paused}
        This account is paused, so nothing will be answered until you resume it.
      {:else}
        Waiting out the cooldown between replies, {countdown(cooling) || "any moment"}.
      {/if}
    </span>
    {#if !entry.paused && entry.cooldownRange}
      <span class="shrink-0 text-[11px] text-faint">
        set to {entry.cooldownRange[0]}, {entry.cooldownRange[1]}s between replies
      </span>
    {/if}
  </div>
{/if}

{#if loading}
  <div class="space-y-2">
    {#each Array(3) as _}<div class="h-20 animate-pulse rounded-xl bg-white/[0.03]"></div>{/each}
  </div>
{:else if users.length === 0}
  <Empty
    text="Everyone has been answered."
    hint="Anyone who messaged this account without a reply appears here, including messages that arrived while the bot was off."
    icon="chats"
  />
{:else}
  <div class="space-y-2">
    {#each ordered as u (u.id)}
      <div class="glass flex flex-wrap items-start gap-x-4 gap-y-3 p-4">
        <Avatar src={u.avatar} name={u.name} size={36} />

        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <!-- Clickable: opens what is stored about them. -->
            <UserChip id={u.id} name={u.name} size="md" />
            <Badge tone="accent">{u.count} unread</Badge>
            <span class="text-[11px] text-faint" title={u.ts ? at(u.ts) : "this session"}>
              {ago(u.ts)}
            </span>
            {#if offline(u.ts)}
              <span class="rounded bg-warn/15 px-1.5 py-0.5 text-[10px] text-warn"
                    title="This arrived while the bot was not running">
                while offline
              </span>
            {/if}
            <!-- Why this one specifically is still sitting here. The bot
                 waits a weighted random 20s to 7min before answering, so a
                 conversation with nothing next to it looks ignored when it is
                 simply not due yet. -->
            {#if entry.paused}
              <span class="rounded bg-warn/15 px-1.5 py-0.5 text-[10px] text-warn">
                held, account paused
              </span>
            {:else if u.reply_at && countdown(u.reply_at)}
              <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent"
                    title="The bot answers this on its own at {at(u.reply_at)}">
                replies {countdown(u.reply_at)}
              </span>
            {:else if u.reply_at}
              <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent">
                replying now
              </span>
            {:else if cooling}
              <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent">
                after cooldown, {countdown(cooling) || "now"}
              </span>
            {:else}
              <span class="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-faint"
                    title="Nothing scheduled: it arrived while the bot was off, or the batch has already fired">
                no reply scheduled
              </span>
            {/if}
          </div>
          <!-- The message itself, given room to actually be read. -->
          <p class="mt-1.5 rounded-lg bg-black/20 px-3 py-2 text-[13px] leading-relaxed text-ink/90">
            {u.snippet}
          </p>
        </div>

        <div class="flex w-full shrink-0 gap-2 sm:w-auto">
          <Button kind="ghost" onclick={() => reply(u)}
                  loading={replyingAll || replying === u.id}
                  disabled={busy}>Reply</Button>
        </div>
      </div>
    {/each}
  </div>
{/if}

{#if archived.length}
  <!-- Answered already. Folded away, because the list above is the work and
       this is the record of it: worth having, not worth being in the way. -->
  <div class="mt-5">
    <button
      class="flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left transition-colors hover:bg-white/[0.04]"
      onclick={() => (showPast = !showPast)}
      aria-expanded={showPast}
    >
      <span class="shrink-0 text-faint transition-transform duration-200"
            style="transform: rotate({showPast ? 90 : 0}deg)">
        <Icon name="chevron" size={13} />
      </span>
      <span class="text-[12px] font-medium text-muted">
        Already answered, {archived.length}
      </span>
      <span class="ml-auto shrink-0 text-[11px] text-faint">
        everyone this account has spoken with
      </span>
    </button>

    {#if showPast}
      <div class="mt-1 divide-y divide-edge/50 rounded-xl bg-white/[0.02] p-1">
        {#each archived as c (c.id)}
          <div class="flex items-center gap-3 px-2 py-2">
            <Avatar src={c.avatar} name={c.name} size={28} />
            <span class="min-w-0 flex-1 truncate">
              <UserChip id={c.id} name={c.name} />
            </span>
            <span class="shrink-0 text-[11px] text-faint">
              {c.messages} message{c.messages === 1 ? "" : "s"}
            </span>
            <span class="w-16 shrink-0 text-right text-[11px] text-faint"
                  title={c.last_ts ? at(c.last_ts) : ""}>
              {ago(c.last_ts)}
            </span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}
