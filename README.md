# hoopwatch

Buzzes your phone when a basketball card box is buyable at or near MSRP.
Nothing else. No daily updates, no market chatter.

---

## The rule it follows

You get an alert only when **all** of these are true:

- It's a basketball box
- MSRP is between **$300 and $4,000**
- You'd pay no more than **15% over MSRP**
- It's actually in stock (or the entry window is open)

Everything else stays silent.

---

## Why Topps' own store matters most

Topps sells at MSRP. Resellers don't.

So the rule is simple: **anything in stock on Topps' site inside your price
range is a buy.** No price comparison needed — that price *is* MSRP.

For resellers, the bot checks the price against your 15% limit first. Most
will be far over and stay quiet.

---

## What an alert looks like

```
🏀 BUY — Topps Chrome Update Basketball — Jumbo
Topps (official): $1,080
At MSRP ($1,080)
Resellers asking ~$2,250 → gap ≈ $1,170

https://launches.topps.com/...
```

Tap the link. Buy it. That's the whole job.

---

## Setup — about 15 minutes, once

### 1. Make the Telegram bot
1. Open Telegram, search **@BotFather**, press Start
2. Send `/newbot`, pick any name, username must end in `bot`
3. It gives you a long token — copy it
4. **Find your new bot and send it "hi".** Required. Telegram won't let a bot
   message you until you've messaged it first.
5. Open this in a browser with your token pasted in:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   Look for `"chat":{"id":123456789` — that number is your chat ID

### 2. Put the files on GitHub
1. Go to github.com/new, make a **public** repo called `hoopwatch`
   (public = unlimited free runtime; your token isn't in the files)
2. Add file → Upload files → drag the whole unzipped folder in at once so
   `.github/workflows/watch.yml` keeps its location

### 3. Paste in your two secrets
Settings → Secrets and variables → Actions → New repository secret

| Name | Paste this |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | the number from step 1.5 |

### 4. Turn it on
1. Actions tab → "I understand my workflows, enable them"
2. Click **hoopwatch** → Run workflow
3. The first run is silent on purpose — it's writing down what everything
   looks like right now so it can spot changes later

---

## It keeps its own list current

Every run, it also reads Topps' launch page and picks up any new basketball
product automatically. You don't have to add anything.

For a newly found product it doesn't know MSRP yet — so it treats Topps' own
price as MSRP, which is correct by definition.

Already watching:

| Box | MSRP | Your max |
|---|---|---|
| Chrome Update — Jumbo | $1,080 | $1,242 |
| Chrome Update — Hobby | $550 | $632 |
| Chrome Black — Hobby | learns it | +15% |
| Chrome Black — Sealed Case | learns it | +15% |

---

## Changing things

Open `products.json`:

- **Willing to pay more?** `max_over_msrp_pct` — change 15 to whatever
- **Price range?** `msrp_min` and `msrp_max`
- **Add a store:** add a `{"label": ..., "url": ..., "role": "market"}` line
  to any product

Commit the change and it takes effect on the next run.

**To stop it:** Actions → hoopwatch → "..." → Disable workflow


---

## Before the first drop: set up EQL

Topps sells its hottest boxes through a lottery called EQL. You enter during a
window, and if you're picked, you're charged automatically.

Do this once, today — not during a live window:

1. Go to topps.com, open any EQL launch page, create an EQL account
2. Complete identity verification
3. Add your shipping address
4. Add your card and clear the bank's 3D Secure check

That last step needs your bank to approve it. Finding that out mid-window is
how people burn an hour they didn't have.

**Two things that surprise people:**

- **Speed inside the window doesn't matter.** Entering at minute 2 or minute
  55 gives identical odds. The window runs about an hour — which is exactly
  why a 10-minute check is plenty.
- **Losing helps you.** Each unsuccessful entry raises your "EQLizer" score,
  improving your odds on that retailer's future drops. Enter every basketball
  window the bot surfaces, even ones you're lukewarm on.

**One entry per person**, enforced by identity checks. Don't have a family
member enter on your behalf — the system is built to catch it.

---

## Honest limits

- **It won't buy for you.** You tap and check out yourself.
- **It can't tell you what's inside a box.** Nobody can.
- **Reseller prices are asking prices, not sold prices.** A "gap" is an
  estimate of resale value, not a promise.
- **Entry windows need your account ready in advance.** The bot catches the
  window opening; everything after that is on you. There is NO purchase-link
  email to race — if you're selected, EQL charges the card you already gave
  them and emails a receipt. The email is confirmation, not a to-do.
- **Topps' launch page may load its list with JavaScript.** If auto-discovery
  never finds anything new, that's why — the fix is adding products by hand
  to `products.json`, and the ones already listed work regardless.
- **Expect long silences.** At today's prices nearly everything is over your
  limit. That's the rule doing its job.
