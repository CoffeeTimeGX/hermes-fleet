# Publishing

`fleet publish` sends a finished video to your channel's accounts. Only Instagram makes
it public at once:

| Platform | What `fleet publish` does | What is left for you |
| --- | --- | --- |
| YouTube | Uploads the video as a **private** video, with its title, description, tags and thumbnail. | Check it in YouTube Studio and publish it, or let it go public by itself at a time you chose with `--at`. |
| TikTok | Sends the video to your TikTok **inbox**. | Open TikTok, tap the notification, paste the caption and post it. |
| Instagram | Posts the video as a **Reel**, public at once. Instagram's API has no drafts. | Nothing. That is why it needs `--now`. |

The fleet uses each platform's official API, through an app of your own and your own
accounts. Each channel has its own accounts. You sign each one in once, on your PC. The
sign-ins stay in your secrets folder, `~/.config/fleet/secrets/publish/`, and never go
to a VPS.

## Quick start

Once the accounts are signed in (see below), bring the video home and send it:

```powershell
fleet pull
fleet publish vps1 20261124-090012-space-facts-k2m9q --to youtube,tiktok
```

```
youtube: uploaded as a private draft, it stays private until you publish it in YouTube Studio: https://studio.youtube.com/video/abc123XYZ00/edit (thumbnail set)
tiktok: the video is in your TikTok inbox: open TikTok, tap the notification, check it and post it. Caption to paste:
Why Saturn's rings are vanishing
...
```

The job id comes from `fleet jobs` or from the message of `fleet pull`. To see what
would be sent, without sending anything, add `--dry-run`.

You can also ask Hermes on Telegram, for example *"put yesterday's Space Facts video on
YouTube and TikTok"*. Hermes posts to Instagram only when you say so in so many words,
because a Reel is public at once.

## What a video needs

`fleet publish` sends the copy on your PC, so run `fleet pull` first. In the job's
`output/` folder it needs:

- the video: the one the [video check](video-check.md) looked at, else `video.mp4` or
  the biggest video;
- `metadata.json` with a `title`, and usually a `description` and `tags`;
- for YouTube, a thumbnail if you want one: `thumbnail.png` or `thumbnail.jpg`.

```json
{
  "title": "Why Saturn's rings are vanishing",
  "description": "Saturn's rings are slowly raining down into the planet. Here is how fast.",
  "tags": ["space", "saturn", "astronomy"]
}
```

The [week plan](week-plan.md)'s jobs ask Claude for all of these. Other keys you can
add:

| Key | Meaning |
| --- | --- |
| `caption` | The words under a TikTok or Instagram post. Without it, the fleet writes the title, the description and up to 8 tags as hashtags. |
| `category_id` | A YouTube category number, such as `"28"` for Science and Technology. |
| `made_for_kids` | `true` or `false`, for this video only. It wins over the channel's answer at sign-in. |
| `synthetic_media` | `true` or `false`, for this video only: YouTube's label for realistic content made with AI. It wins over the channel's setting. |

When the video check found problems, `fleet publish` stops and says which. Make the
video again with `fleet retry`, or send it as it is with `--anyway`.

## YouTube

**Once, for all your channels:** an app of your own in Google Cloud. It is free.

1. Open the [Google Cloud console](https://console.cloud.google.com/) and create a
   project, for example `fleet publish`.
2. Open **APIs & Services**, then **Library**. Find **YouTube Data API v3** and click
   **Enable**.
3. Open **Google Auth Platform** and click **Get started**. Give the app a name, choose
   your own email address as the support and contact address, choose the audience
   **External**, and finish.
4. On the **Audience** page, click **Publish app**, so that its status is
   **In production**. Leave it in **Testing** and Google signs you out after 7 days.
5. On the **Clients** page, click **Create client**. Choose the application type
   **Desktop app** and click **Create**.
6. Click **Download JSON** in the window that shows the new client. Google shows the
   secret only then.
7. Save that file as `youtube-client.json` in the publish folder:

    ```powershell
    New-Item -ItemType Directory -Force "$HOME\.config\fleet\secrets\publish"
    Move-Item "$HOME\Downloads\client_secret_*.json" "$HOME\.config\fleet\secrets\publish\youtube-client.json"
    ```

    On Linux and macOS:

    ```bash
    mkdir -p ~/.config/fleet/secrets/publish
    mv ~/Downloads/client_secret_*.json ~/.config/fleet/secrets/publish/youtube-client.json
    chmod 600 ~/.config/fleet/secrets/publish/youtube-client.json
    ```

    If you closed the window too early, write the file yourself with the client ID and
    secret: `{"installed": {"client_id": "", "client_secret": ""}}`.

**Then, for each channel:**

```powershell
fleet publish --login youtube --channel "Space Facts"
```

1. It asks whether the channel's videos are made for kids. YouTube asks this of every
   video, by law. Answer `yes` or `no` (or give `--made-for-kids no` on the command).
2. Your browser opens Google's sign-in. Pick the Google account, and the channel if
   Google asks.
3. Google warns that it has not verified the app. That is expected: the app is yours.
   Click **Advanced**, then **Go to** your app's name.
4. Allow the access it asks for. The browser says "Signed in", and so does the terminal.

The fleet marks every upload as **altered or synthetic content**, YouTube's label for
realistic content made with AI, because Claude made it. If your channel's videos do not
need the label, sign in with `--no-ai-label`.

**Good to know**

- YouTube allows 100 uploads a day through the API for your Google Cloud project.
- A custom thumbnail needs a verified channel (YouTube verifies it with your phone).
  Without one, the upload works and the command says `thumbnail not set`.
- `--at "2026-12-01 18:00"` makes the video go public by itself at that time, in your
  PC's time. It must be at least 15 minutes ahead.

## TikTok

TikTok must approve your app before it can upload. Its review takes several days to
two weeks, so start early.

**Once, for all your channels:** an app of your own on TikTok for Developers.

1. Sign in at [TikTok for Developers](https://developers.tiktok.com/). Click your
   profile icon, then **Manage apps**, then **Connect an app**. Choose yourself as the
   owner and click **Confirm**.
2. Fill in the app's details. TikTok wants a website with a terms of service page and a
   privacy policy page, and it checks that the website is yours.
3. Under **Products**, click **Add products** and add **Login Kit** and
   **Content Posting API**.
4. In Login Kit, add the redirect URI for Desktop, exactly as written:
   `http://127.0.0.1:8741/callback/`
5. Under **Scopes**, make sure the app has `user.info.basic` and `video.upload`.
6. Under **App review**, explain how the app works: *"I upload my own channel's videos
   from my own computer to my TikTok inbox, and I post them myself in the TikTok app."*
   Upload a short demo video of that, then click **Submit for review**.
7. Run the sign-in once. It creates the file for your app's keys and stops:

    ```powershell
    fleet publish --login tiktok --channel "Space Facts"
    notepad "$HOME\.config\fleet\secrets\publish\tiktok-app.json"
    ```

    Fill in the **client key** and **client secret** that your app's page shows, and
    save.

**Then, for each channel**, run the sign-in again:

```powershell
fleet publish --login tiktok --channel "Space Facts"
```

Your browser opens TikTok. Sign in with the channel's TikTok account and allow the app.
Until TikTok has approved `video.upload`, the sign-in works but uploads do not, and the
command says so.

**Good to know**

- Each upload waits in your TikTok inbox until you post it. TikTok allows at most 5
  waiting uploads in 24 hours, so post them or delete them as they come.
- The caption does not travel with the upload. `fleet publish` prints it, ready to
  paste.
- A TikTok sign-in lasts about a year. The daily report tells you 30 days before it
  ends.

## Instagram

Instagram's API has no drafts: the Reel is public as soon as it is posted. That is why
the command needs `--now`.

**What the account needs:** it must be a professional account (Business or Creator),
and public. You switch an account in the Instagram app's settings.

**Once, for all your channels:** a Meta app of your own.

1. Open [Meta for Developers](https://developers.facebook.com/), then **My Apps** and
   **Create app**. Choose the use case **Other**, then the app type **Business**.
2. Add the **Instagram** product (**Set up**). It brings **API setup with Instagram
   login**.
3. Meta may ask for **App Review** before your app can post (its docs say an app needs
   it to work with live data). If a post is refused for that reason, ask for
   `instagram_business_basic` and `instagram_business_content_publish` in App Review.

**Then, for each channel:**

1. In your app's dashboard, open **Instagram**, then **API setup with Instagram login**.
   Under **Generate access tokens**, add the channel's Instagram account (you sign in to
   Instagram), then click **Generate token** next to it, and copy the token.
2. Paste it here. It is not shown while you paste:

    ```powershell
    fleet publish --login instagram --channel "Space Facts"
    ```

If Instagram does not say which account the token is for, add `--ig-user-id` with the
account's Instagram user id.

**The video needs a public link.** Instagram fetches the video from the internet, so
the fleet shares it for a few minutes on a secret link with
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel), then switches the link off:

- Your PC needs Tailscale with MagicDNS on.
- The first time, Tailscale may print a link to turn on HTTPS and Funnel for your
  tailnet. Open it, allow it, and run the command again.
- On a Mac, Tailscale's apps (from the App Store or from Tailscale's website) cannot
  share a file. Give the link yourself, as below.

If the video is already on a public website of yours, give its link instead:
`--video-url https://...`. It must start with `https://`.

```powershell
fleet publish vps1 20261124-090012-space-facts-k2m9q --to instagram --now
```

**Good to know**

- Instagram allows 100 posts a day through the API for each account.
- A token lasts 60 days. The fleet makes it new each time you post, once it is a day old.
  When an account has not posted for 45 days, the daily report reminds you to make a
  new token.

## All the options

```powershell
fleet publish vps1 <job-id> --to youtube                           # a private YouTube video
fleet publish vps1 <job-id> --to youtube --at "2026-12-01 18:00"   # public by itself at that time
fleet publish vps1 <job-id> --to youtube,tiktok,instagram --now    # all three
fleet publish vps1 <job-id> --to youtube --dry-run                 # say what would be sent
fleet publish vps1 <job-id> --to youtube --anyway                  # even if the video check found problems
fleet publish vps1 <job-id> --to youtube --channel "History"       # another channel's accounts
fleet publish --accounts                                           # the signed-in accounts
```

Without `--channel`, the fleet uses the accounts of the job's own channel. `--json`
prints the answers as JSON.

**What is kept:** each job's folder gets a `publish.json` with what went where, and
`publish.jsonl` in your results folder keeps every attempt. The
[daily report](scheduled-checks.md#the-daily-report) counts what was sent.

**Sign in again** any time with the same `--login` command. It replaces the old
sign-in. To sign a channel out, delete its file in the publish folder, such as
`youtube-space-facts.json`, and remove the app's access in the account's settings on
the platform.

## If something goes wrong

| Message | What to do |
| --- | --- |
| `... is not on this computer yet: run fleet pull ...` | Run `fleet pull`, then try again. |
| `output/metadata.json has no title` | The job did not write its details. Write `metadata.json` in the job's `output/` folder yourself, or make the video again. |
| `no Google app yet` | Do the "Once" steps of [YouTube](#youtube). |
| `Sign in again: fleet publish --login youtube ...` | The sign-in ended. An app left in **Testing** signs you out after 7 days: publish it (step 4), then sign in again. |
| `fill in your TikTok app's client key and secret` | Step 7 of [TikTok](#tiktok). |
| `TikTok did not grant video.upload` | TikTok has not approved the app yet. Wait for its review. |
| `Instagram has no drafts` | Add `--now` when you want the Reel public at once. |
| `Tailscale Funnel did not start` | See [the video needs a public link](#instagram), or give `--video-url`. |
| `the video check found problems` | Make the video again with `fleet retry`, or add `--anyway`. |
