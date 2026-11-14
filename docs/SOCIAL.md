# Morrow Brief: the social pages

Morrow Brief is Morrow's page on Telegram, Instagram, Threads and X. It posts one digest a day and a few alerts,
all taken from the published edition at https://juw12.github.io/morrow/. A Telegram bot answers questions about
the day's edition.

> Tech and markets, read across the outlets. One brief a day, every story sourced.

Nothing here is live yet. The code is tested, but no page account, API key or bot token exists, so no post has
been sent. [What is not verified](#what-is-not-verified) lists every part that has only been tested against fakes.

## Why this page, when AI news channels already exist

The closest comparison is Girsta AI News (`t.me/girsta`), an automated English AI news channel on Telegram. Morrow
Brief is built to differ in ways a reader sees in the posts themselves:

| | Girsta AI News | Morrow Brief |
|---|---|---|
| Volume | automated posts through the day | one digest of 5 stories, plus at most 4 alerts a day |
| Scope | AI | AI and chips, big tech, robotics, space, tech, plus a market line |
| Platforms | Telegram | Telegram, Instagram, Threads, X |
| Bot | none found | section commands and `/find <word>` |

The table holds only what could be compared. The Girsta column comes from a secondary source (Telepick, about 486
subscribers); the channel could not be opened from the machine this was built on, so how Girsta sources its
posts, what its images look like and how it writes were not checked and are not compared.

Three more things are true of Morrow Brief on their own account, whatever a competitor does:

- **Sourcing.** Every story says how many outlets report it, and the lead links to each one the page names.
- **Cards.** Each post carries its own typographic card: a red bar on the top edge, the headline, and the outlet
  count as a large numeral. No publisher photos.
- **Tone.** No emoji, and a plain statement that the selection is automated.

## What gets posted

**The digest** goes out once a day, on the first edition published between 06:00 and 22:00 Jakarta time (WIB).
It holds 5 stories: the page's lead story, then the stories the most outlets report, with at most 2 from any
one section. If the edition has fewer than 3 stories, no digest is sent.

**An alert** is a single story outside the digest that 3 or more outlets report. Alerts are limited to 4 a day,
at least 90 minutes apart, between 06:00 and 22:00 WIB. Most days have none or one. On Telegram an alert arrives
silently; only the digest sends a notification.

No story is posted twice in a day, and a story in the digest is never sent again as an alert.

Each platform gets its own format:

| Platform | Digest | Alert | Limit enforced |
|---|---|---|---|
| Telegram | cover card with a caption: 5 linked headlines, section, outlet count, a link to each outlet the page names for the lead, market line | card, headline, summary, a link to each outlet the page names | 1024 |
| X | thread of 5, one post per story: headline, a one-sentence summary where it fits, outlets, source link; cover card on the first | one post with the card | 280, links counted as 23 |
| Threads | one post: as many whole headlines as fit (at least 3), the rest named by outlet, linking to the edition | headline, summary, source link | 500 |
| Instagram | carousel: cover and one card per story; the caption gives each story a summary and names its outlets | one card | 2200 |

Instagram captions cannot hold links, so they name the outlets and point to the link in the bio.

An X post often has no summary. After the headline, the outlets and the link there is rarely room for a whole
sentence, and half a sentence is not sent. In today's thread the first post has 76 characters free and the
lead's first sentence is 213 characters long, so it goes without. The card on that post carries the summary.

Rules that hold for every post, each checked by a test:

- every story names its source outlet and says how many outlets report it;
- no emoji, in text or on cards (`▲`, `▼` and `•` are the only marks used);
- a post over its platform limit is never sent;
- a summary is kept as whole sentences or left out, never cut mid-sentence, in captions and on cards alike.
  When an outlet's own feed ends a summary mid-sentence, that fragment is dropped. A headline is shortened (at a
  word boundary, with an ellipsis) only when the post would not fit otherwise; today's digest shortens none;
- cards are 1080 x 1350, drawn from text alone (no publisher photos), with every colour pair at 4.5:1 or better.
  The cover sets the lead headline large (at least 1.6 times the rows when the text allows), with the other
  four as numbered rows and the market moves below;
- Instagram captions carry this line: "Automated selection from published reporting. Headlines belong to their
  outlets; every story names its source."

Run `python scripts/social_post.py preview --page index.html --out preview` to see exactly what today's edition
would post. It writes `preview/preview.md`, the cards, and the request bodies, and sends nothing. The "Morrow
Brief" workflow attaches the same preview to every pull request as the artifact `morrow-brief-preview`.

## How it runs

```
private generator --push--> index.html on main
                                 |
                  .github/workflows/social.yml
                                 |
        tests -> build -> save -> deliver -> save
                                 |
              branch social-data: state.json, feed.json, cards/
                        |                         |
           Buffer fetches the cards      the bot reads feed.json
```

1. The private generator pushes a new `index.html`. That push starts the workflow. The workflow also starts
   itself every 3 hours as a fallback; a run that finds nothing new posts nothing.
2. The tests run. If they fail, nothing is posted.
3. `build` reads the page, decides whether a digest or alert is due, draws the cards and freezes the post into
   `state.json`. A frozen post is never rewritten, even if the page changes before it is sent.
4. The state is saved to the `social-data` branch, and only then does `deliver` send: Telegram directly, and
   Instagram, Threads and X through Buffer's API.
5. The results are saved again.

State, cards and the bot's feed live on the `social-data` branch and never touch `main`, so the workflow cannot
collide with the generator's pushes. Each run replaces the branch with a fresh commit, so it does not grow. Posts
and cards older than 7 days are dropped.

Buffer's free plan allows 3 channels, which is why there are three Buffer platforms. Telegram is sent directly
because Buffer does not support it.

## What happens when something goes wrong

Every target (one platform for one post) has a status in `state.json`. The run summary in the Actions tab lists them.

| Status | Meaning | Sent again? |
|---|---|---|
| `pending` | frozen, not yet tried | yes |
| `sending` | claimed by a run that is about to send it | only by that same run |
| `delivered` | the platform accepted it | no |
| `failed` | a clear refusal or a network error before anything was sent | yes, up to 3 attempts |
| `gave_up` | failed 3 times | no |
| `unconfirmed` | the request may or may not have gone through | no |
| `skipped` | the platform has no credentials | no |
| `expired` | still unsent 3 hours after it was frozen | no |

The design rule is that a post may be lost but must never appear twice.

- **The run dies halfway.** Before sending, a run marks its targets `sending` with its own run id and saves that.
  If it dies, the next run finds a claim that is not its own and marks the target `unconfirmed` without sending.
- **A timeout or an unreadable reply.** The target becomes `unconfirmed` and is left alone.
- **The data branch cannot be read.** The run fails before posting. Only a branch that does not exist yet
  (the very first run) starts from an empty state.
- **The page is stale.** If the edition's date is not today in WIB, nothing is frozen.
- **A wrong channel.** Buffer posts go only to channel ids listed in the variable `MORROW_BUFFER_CHANNELS`. A
  key that also holds other channels cannot post to them, and with the variable empty nothing is sent to Buffer.
- **Secrets are added later.** Targets skipped while a platform had no credentials stay skipped, so adding a
  secret does not release a backlog of old posts.
- **A card is not yet served.** `deliver` waits up to 90 seconds for the first card URL to answer, then tries
  the second URL, and fails the target (to be retried) if neither serves it.
- **Two runs at once.** The publish job is in one concurrency group, so runs queue.

## The Telegram bot

The bot answers from `feed.json`, which holds ready-made replies for the day. It stores nothing: no subscriber
list, no chat ids, no message history.

| Command | Reply |
|---|---|
| `/start`, `/help` | what the bot does and the list of commands |
| `/today` | the day's digest |
| `/ai`, `/bigtech`, `/robotics`, `/space`, `/tech` | that section's stories |
| `/markets` | the markets stories |
| `/tape` | index moves, one per line |
| `/sources` | the story and outlet counts, and every outlet's name |
| `/find <word>` | up to 6 stories whose headline, summary, topic tag or outlet contains every word given |
| `/about` | what Morrow Brief is and how stories are chosen |

There are two ways to run it. Use one.

- **Cloudflare Worker (recommended).** `bot/worker.js` answers each message as it arrives. It holds no bot token:
  it replies in the webhook response itself. Its only secret is `WEBHOOK_SECRET`, which Telegram sends back with
  every call so the Worker can refuse anyone else.
- **GitHub cron (fallback).** The "Morrow Brief bot" workflow polls every 5 minutes and listens for 4 minutes each
  time. GitHub often starts scheduled runs late, so replies can take several minutes. The schedule does nothing
  until the variable `MORROW_BOT` is `on`; until then the Actions tab shows a skipped run every 5 minutes, and
  the workflow can be disabled there if the Worker is used.

If a webhook is set, polling is refused by Telegram; the poller logs that and stops.

## Setup

Until these steps are done the workflow runs, records every target as `skipped` and posts nothing.

1. Create the page accounts: a Telegram channel, an Instagram professional account, Threads and X. Suggested
   handle `morrowbrief`, with `readmorrow` or `morrowdaily` as fallbacks. None of these has been checked for
   availability.
2. In Telegram, create a bot with @BotFather and add it to the channel as an admin that can post.
3. In Buffer, connect the Instagram, Threads and X accounts and create an API key. A separate Buffer account for
   Morrow Brief keeps it apart from any personal channels.
4. List the channel ids:
   ```
   BUFFER_API_KEY=... python scripts/social_post.py channels
   ```
5. In the repo settings, add:

   | Kind | Name | Value |
   |---|---|---|
   | secret | `BUFFER_API_KEY` | the Buffer key |
   | secret | `TELEGRAM_BOT_TOKEN` | the token from @BotFather |
   | secret | `TELEGRAM_CHAT_ID` | the channel, as `@handle` or its numeric id |
   | variable | `MORROW_BUFFER_CHANNELS` | the three channel ids, comma separated |

6. Run "Morrow Brief" once from the Actions tab and read the run summary.

For the bot, either:

- create a Cloudflare Worker, paste in `bot/worker.js`, and add a Worker secret `WEBHOOK_SECRET` (any long random
  string). Add the same string to the repo as the secret `TELEGRAM_WEBHOOK_SECRET`. Then run "Morrow Brief bot"
  from the Actions tab with action `set-webhook` and the Worker's URL; or
- set the repo variable `MORROW_BOT` to `on`.

To stop posting, disable the "Morrow Brief" workflow in the Actions tab. To stop one platform, remove its id from
`MORROW_BUFFER_CHANNELS`, or remove the Telegram secrets.

## What is not verified

Tested here means unit tests against fake HTTP servers, plus a rehearsal of the workflow's git steps against a
local repository. The following have not been run against the real services:

- a real Buffer `createPost`. The request shape follows Buffer's live schema, read by introspection;
- a real Telegram send, and a real webhook call to the Worker;
- the Worker deployed on Cloudflare (its tests run under Node);
- whether Buffer and Instagram accept card images served from `raw.githubusercontent.com`;
- whether X shows the cover card once or repeats it in the thread;
- whether Threads counts a link at full length (the code assumes it does);
- whether the generator's pushes start the workflow. A push made with the default `GITHUB_TOKEN` of another
  workflow would not; a push with a personal token or deploy key does. If they do not, the 3-hour schedule still
  posts, but the digest can be up to 3 hours later than the first edition and alerts arrive in 3-hour steps.
  GitHub pauses schedules in a repository with no activity for 60 days;
- the publish job itself, which cannot run until this is on `main`;
- handle availability, and the Girsta figures above.

## Files

| Path | What it does |
|---|---|
| `scripts/social_feed.py` | reads the edition, picks the digest and alerts, writes the text for each platform |
| `scripts/social_cards.py` | draws the cards |
| `scripts/social_post.py` | `build`, `deliver`, `channels`, `preview` |
| `scripts/social_bot.py` | the polling bot, and `set-webhook` / `delete-webhook` |
| `scripts/social_save.sh` | saves the data folder to the `social-data` branch |
| `bot/worker.js` | the webhook bot |
| `tests/social/` | Python tests; `bot/worker.test.mjs` holds the Worker's |
| `assets/fonts/` | Source Serif 4 and Source Sans 3, under the SIL Open Font License |

Run the tests with:

```
pip install -r scripts/social_requirements.txt
python -m unittest discover -s tests/social
node --test bot/worker.test.mjs
```
