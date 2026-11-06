# Community profiles

Profiles people made in LLMSelfbot and shared for anyone to add. Browse them in the app (**Profiles, Community**) or on
this repo's [web page](https://miiazertyy.github.io/LLM-Selfbot/).

There's no server: it all runs on this repo.

| | |
|---|---|
| The profiles | The [`community-data`](https://github.com/miiazertyy/LLM-Selfbot/tree/community-data) branch: a folder each, with its text, settings, face and thumbnails. It never touches the app's code. |
| Downloads | The **Community profiles** release: one file per version. GitHub counts every download, and those counts are the stats. It's a pre-release, so it's never taken for a version of the app. |
| Requests and reports | Issues labelled `profile-...`, opened by the app. They close themselves once handled. |
| The work | The **Community** workflows in `.github/workflows`, with the scripts in `community/scripts`. |

## What a profile is

- Its text: who it is and how it talks.
- The part of its settings that says how it talks: moods, reply length, reactions, its voice. Never models, keys,
  limits, accounts or anything an account does on its own.
- Its face, and pictures and short videos its author picked.

Never its memory, its chats, its accounts or anything else on the author's computer.

## Sharing one

Everything happens in the app. Sign in with GitHub once (the app shows a code to enter on github.com), check the
preview, and press Send. The sign-in only lets the app open issues here and keep your own private gist for the
pictures and videos. It can't see or change anything else on your GitHub.

Your request is checked automatically and goes live within a minute or two if it passes, or comes back with what to
fix. You can send updates to your own profiles and remove them the same way. Nobody else can.

Every profile shows its version and the app version it was made with, so people see whether it's up to date with
their app. Sending an update from a newer app brings it up to date.

**Everything you send is public**, even a request that doesn't pass. The app shows you exactly what goes out first.

## The rules

- No scams, tricks, links, invites or payment details.
- No private information about anyone.
- No real people without their consent.
- No hate or harassment, and nothing sexual involving minors. Mark anything adult as 18+.
- Don't copy someone else's profile and send it as yours.

Moderators take down what breaks these, and can stop an author from sending again.

## Stats

Adding a profile downloads its file from the Community profiles release, and GitHub counts each download. Those counts
are read every hour, and once a day they're kept as a point in `stats/history.json` on the data branch, which the app
draws as charts.

## For moderators

Comment on a request, a report, or the moderation log the app makes:

| Command | What it does |
|---|---|
| `/takedown <slug> [reason]` | Out of the catalog now. It can be restored. |
| `/restore <slug>` | Back as it was before the takedown. |
| `/ban <slug or @login> [reason]` | That author can't send anymore, and their profiles are taken down. |
| `/unban <slug or @login>` | They can send again. |
| `/close` and `/open` | Pause or resume sending for everyone. |
| `/recheck [issue]` | Look at a request again. Its author can use it too. |

Commands on the app's own issues do nothing. Reports come in as issues labelled `profile-report`; nothing happens to a
profile until a moderator acts.

Moderators, limits, tags and banned words are in `community.json` on the data branch. Edit it there on GitHub.

If GitHub ever pauses **Community: site** (it does to scheduled workflows after 60 days without activity), it's turned
back on by the next request, or from the Actions tab.
