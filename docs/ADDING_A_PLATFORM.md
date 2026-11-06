# Adding a platform, and fixing one that broke

Every social the app runs accounts on goes through the same few parts. This is what they are, what to write for a new
one, and where to look when one stops working because the site or its library changed.

## How a platform is put together

| Part | Where | What it does |
| --- | --- | --- |
| The table | `app/platforms/registry.py`, and `webui/src/lib/platforms.ts` for the panel | Its id, name, colour, what its files and ids start with, what kind of thing it is. The lists of platforms everywhere else are made from these. |
| The runner | `app/platforms/snapchat/<id>_runner.js` and `<id>bot.js` | Node. Reads what came in and sends what goes out. Talks to the bridge through files in `ipc/` (`runner_core.js`). A website keeps its selectors in a `SEL` table at the top of its bot. |
| The bridge | `app/platforms/snapchat_bridge.py`, its `PLATFORMS` table | Python. One per account. Answers what the runner read, through the same reply engine every platform uses. |
| Accounts | `app/web/routes/account_routes.py`, its `PLATFORMS` table | Which `.env` names hold an account's login. Secrets go here and nowhere else. |
| Settings | `resources/config.yaml`, `app/web/schema.py`, `app/web/descriptions.py`, `webui/src/lib/settingsmap.ts` | Each key needs all four: a default, a type, words, a home on a tab. `tests/test_whatsapp.py` fails on any that reaches the panel and not the runner. |
| Its setup page | `webui/src/lib/components/SnapchatSetup.svelte` (needs an install) or `PlatformReady.svelte` (does not) | The "ready to run" card. Both are `ReadyHero`'s look. |
| Its logo | `webui/src/lib/brands.ts`, `Icon.svelte`, the `.settings-mark` table in `app.css` | The mark, measured: same area as the others, dead centre, as the comment above that table says. |

Discord and Telegram are Python all the way down (`discord_runner.py`, `platforms/telegram`), and Minecraft and WhatsApp
have no browser, but they still fit the table above.

## Adding one

1. **Add its row** to `registry.py` and to `platforms.ts`.
2. **Run `python tests/test_platform_registry.py`.** It says which parts still do not know the new platform, by file. Work
   down the list.
3. **Write the runner.** Copy the closest existing one: `reddit_runner.js` and `redditbot.js` for a website,
   `whatsapp_runner.js` for a protocol with a library. `runner_core.js` gives you the files, the state the panel shows
   and the send governor, so the runner only has to read and send.
4. **Add its logins** to `account_routes.PLATFORMS`, and its entry to the bridge's `PLATFORMS`.
5. **Add its settings**, every key in all four places. Run `tests/test_whatsapp.py`.
6. **Add its setup page and logo**, and a tab in `settingsmap.ts`.
7. **Say what it cannot do.** `app/utils/compat.py` for what a phone or an OS cannot run, and `calls`, `voice`, `stories`
   and the rest in `platforms.ts`, which is what the pages ask rather than asking which platform it is.

A website has no account to test with at first, usually: write a `<id>_probe.js` beside the runner, as the others have,
that prints what its page really contains. Guessed selectors fail silently.

## When a website changes

The account's card says so: `SiteWatch` (`sitewatch.js`) looks for the few things that should always be on the page, on
tabs the runner already has open, and what has been missing for three looks in a row goes on the card as "may have
changed its page". It opens nothing and loads nothing, so it is safe on an account that locks when probed.

To fix one:

1. **Find what it looks like now.** Run its probe from the data folder's `snapchat` directory with the account stopped,
   for example `node x_probe.js`. Only one probe session on Snapchat, ever: it locks the account on repeated sign-ins.
2. **Try the fix without a new build.** Put it in `config/sitefixes/<platform>.json` in the data folder:

   ```json
   { "composer": ["div[role=textbox][data-new-name]"] }
   ```

   The names are the ones in that bot's `SEL` table. What you give goes in front of what is there, so a wrong one costs
   nothing, and it is read when the runner starts. Restart the account. Snapchat has no table: its selectors are written
   where each is used in `snapbot.js`, and a fix there needs a build.
3. **Make it permanent** by moving it into `SEL`, and put the page you probed in `tests/fixtures/` if its parser reads it.

## When a library or a version changes

| Platform | What moves | Where the fix goes |
| --- | --- | --- |
| Discord | `discord.py-self` falls behind what Discord accepts, or its voice encryption changes | The pin in `requirements.txt`. The client build it claims is Settings, Discord, Client, and "Custom" overrides it. |
| WhatsApp | `baileys` needs a newer protocol | The pin in `app/platforms/snapchat/package.json`. Its install runs again from its Setup page. |
| Telegram | `telethon` falls behind Telegram's layer | The pin in `requirements.txt`. |
| Minecraft | A server newer than mindcraft knows | `app/platforms/minecraft/install.py` for mindcraft itself, and ViaProxy for a server on another version, from its Setup page. |
| iMessage | BlueBubbles Server's API, or the Shortcuts steps | `bluebubbles.js`, and the steps in `ImessageSetup.svelte`. |
| Snapchat, TikTok, Instagram, X, Reddit | `puppeteer` against a new Chrome | The pin in `package.json`. Their pages are the section above. |

`package.json` changes reach installed copies by themselves: the bridge copies the runner into the data folder on every
start, and asks for an install when its dependencies differ.

## The rules every platform follows

- A person's credentials go in `config/.env` through `account_routes` and nowhere else.
- A social that is switched off shows nowhere (`app/utils/socials.py`, `webui/src/lib/socials.ts`).
- Anything that can be turned on has to reach the runner: an environment variable from the bridge, or the config file.
- What it cannot do is said in words on the page, rather than a control that does nothing.
- A persona made from your chats (`app/utils/chatpersona.py`) reads the data export the social lets you download. Add a
  parser to `app/utils/chatexports.py` that returns the owner's messages only, and how to get the export to
  `webui/src/lib/personas/exports.ts` with its logo,
  telling whose they are from the export itself; a file it cannot be sure about is set aside with a line saying why.
