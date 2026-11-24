# Family Daily Tracker

A private Odoo 17 setup for family, running in Docker and reachable
over [Tailscale](https://tailscale.com/) HTTPS as a home-screen app on iPhone. Not a generic
Odoo project — every screen is built for a phone.

## Highlights

**📷 Scan a barcode, done.** Point your phone's camera at a product in the store and it's on
the shopping list — or marked bought, or marked finished — in one tap. No typing, no searching
the catalog. First time you scan a barcode, [Open Food Facts](https://world.openfoodfacts.org/)
fills in the name, photo and nutrition facts automatically.

**⚖️ Step on the scale, see it in the app.** If you weigh in on a Xiaomi/Zepp Life smart scale,
your weight can sync itself: Zepp Life → Apple Health → an iPhone Shortcut → straight into your
weight graph. No manual entry, no mixing up who weighed in — each person's own Shortcut carries
their own key.

## Modules

### `family_tracker` — Groceries + shared shell
- **Barcode scanning** (`/groceries/scan`): scan to add to the shopping list, scan again at
  checkout to mark it bought, scan once more when it's finished. Works from the phone camera in
  Safari (camera access needs HTTPS).
- **Product catalog** auto-filled from Open Food Facts: photo, Nutri-Score, full nutrition
  facts per 100 g/ml. Product photos download in the background so scanning stays fast.
  Open Food Facts never overwrites what you have on its own: when its name or kcal / protein / fat / carbs
  differ from yours (it is re-checked nightly, 40 products at a time, and on "Refresh"), you get a banner on
  Shopping List & Stock, a list under Groceries > Open Food Facts changes, and a side-by-side window with
  "Update from Open Food Facts" / "Keep what I have". Store-brand codes (8 digits starting with 2) are
  sometimes reused for different products in other countries, so look before you update.
- **Shopping list & stock**, kanban or list, with low-stock and essentials tracking.
- **Shopping List** (its own green Home tile): a plain checklist for the store, meant to replace a
  note on the phone. Lines are plain words ("milk", "garlic", "buckwheat" - whichever milk is on the
  shelf), with suggestions from what was written before; scanning a barcode adds a specific
  product instead. Tapping a line strikes it through in place with a green tick (tap again to undo);
  for a scanned product that also means bought (it goes In Stock, and scanning it In Stock at
  checkout ticks it too). Ticked lines stay until "Clear ticked" or the next day.
  The list is laid out by **store section**, in the order Ruslana walks through the store (Fruit &
  veg, Meat & fish, Dairy, Flour & baking, Eggs, Frozen, Pasta & grains, Water & drinks, then
  Sweets, Household, Other - reorder/rename under Groceries > Store sections). A word goes where it
  went last time; a new one ("куриные бедра", "garlic") is sorted by the assistant once and
  remembered; "⋮" on a line moves it (and that word from then on) to another section.
- The **shared shell** every other module plugs into: theme colours, the phone bottom tab bar,
  the Home page, and the PWA (`Add to Home Screen` on iPhone gives you a real app icon, no
  Safari chrome).

### `family_gym` — Gym & Fit
- **Weight**: log it by hand, or let the scale do it (see below). Last measurement, BMI and a
  bright history chart with a period picker; switch on a **plan curve** (set your goal, age,
  height and gym visits per week and it works out the kcal a day and draws the path to your
  target date) and/or your partner's line on the same chart.
- **Exercises**: one day at a time, like the Meals diary. Log an exercise right at the top
  (pick or type a new one, a row per set: weight and reps), mark that you were at the gym, and
  mark the day as a **Gym Day** and pick one or more kinds of training (Legs / Upper / Back / Cardio / Full body) even without logging
  exercises, and see the whole month as a calendar of squares: green on days you trained, labelled
  with the type (or the muscle groups of the exercises you did). A progress chart follows any exercise's best set.
- **Meals**: a food diary (breakfast/lunch/dinner/snacks) with calories and macros pulled from
  the product catalog; every food shows its protein / carbs / fat (P: C: F:) so you can see where
  the totals came from. "+" on a meal offers Groceries (with a barcode-scan button), My Saved Food
  and **Restaurants**: McDonald's, KFC, Burger King, Subway and Berlin Döner Kebap with their Polish
  menus (logos, kcal and macros per portion, menu combos). Under them a **History** of what you
  ate lately (from any source) adds it again with last time's amount. The **Me / other person**
  switch at the top opens the other's diary, so one of you can fill in what the other ate. Recipes
  can be filed under **categories** (Breakfast, Soups, ... - add, rename or delete your own): My Saved
  Food has a filter row, groups the dishes by category, and a tag button on each dish files it in one tap.
  can use **other recipes as ingredients** (crepes + a filling; change the filling and every dish
  using it follows) and can be edited right from the open recipe.
- **Goals**: personal targets per person.

### `family_finance` — Finance
- **Overview**: one month at a glance - a card per person: their income minus what *they* paid
  ("Paid by" on every expense) and put aside = what is left of it, with where it went by category;
  grocery spending split into food and household, a 6-month trend and the plans being saved for.
- **Expenses**: seven categories as big buttons - Groceries, Housing, Subscriptions, Restaurants,
  Personal care, Clothes, Car, Other. "+ Add expense" asks for the category first, then opens that category's
  entry window.
  - **Groceries**: just the receipt total plus how much of it was household items (cleaning
  supplies, toilet paper...); the rest counts as food. No per-product prices to type in. Pick the
  store, and attach photos of the receipt.
  - **Housing**: rent and utilities, counted in the month they are *for*, with receipt photos.
- **Income**: each payment as it arrives (salary varies), for each of you, in the currency you
  got it in (hryvnias, zlotys...). Both of you see everything, each can only edit their own.
- **Savings**: move money from your income into savings (general, or for a plan) and take it out
  again; kept per currency (dollars/USDT), with what it is worth in zlotys today.
- **Currencies**: books are in PLN; every entry (expenses, income, savings) can be in UAH/USD and is
  converted at the National Bank of Ukraine's official rate for the day (editable). The overview
  and limits always add up in zlotys.
- **Plans**: trips and big purchases as cards in three stages - **Planning** (an idea with a price
  tag), **Saving** and **Done**. A plan has a photo, a date, a budget split into items, a progress
  bar and "X a month to make it". **Move savings here** assigns money you already put aside (from
  either of you, in any currency) to a plan, or takes it back; Planning turns into Saving by itself.
  **Done** can take the saved money out of the savings (paid) - reopening gives it back. Moves are
  not new saving, so the month's numbers do not change.
- **Savings limit**: a transfer from income cannot be more than what is left of that person's income
  in the month (income - what they paid - already saved). The Savings tab lists "You can transfer" per
  person and the transfer window shows the limit with a "Use all" button.
- **Limits**: monthly limits per category and for everything together; the overview turns
  amber at 80% and red when you go over.

### `family_ai` — Assistant (Claude)
- **Push notifications on the iPhone**: the "Помощник" card on Home turns them on for this phone
  (open Family from its home-screen icon, iOS 16.4+). It uses the web push Odoo's mail module
  already has, so there is no extra push service. "Тестовое уведомление" asks Claude for a hello and pushes it;
  tapping a notification opens the whole message, and "Сообщения" lists them all.
- **Evening protein tip** (19:00-21:00 your time, once a day, only when you logged something
  today and are 20 g+ below your protein goal): a realistic set of normal portions of what is
  **in stock at home** (best protein per kcal first, one protein shake at most), with grams, protein
  and kcal, keeping an eye on the calories you have left.
- **Finance, mid-month (the 15th)**: silent when all is fine; otherwise which categories are heading
  over their limit (or, without a limit, well above last month). Only groceries, restaurants and
  personal care are projected by pace - rent, subscriptions, clothes, car and other are paid in lumps
  and count as paid.
- **Finance, month report (the 1st)**: excellent / good / tight / in the red (decided by the
  share of income left after spending: 30% / 15% / 0%), main categories and what changed versus a
  fully tracked previous month, your own numbers, the plans being saved for, and one tip.
- **Chat** (the speech-bubble icon in the top bar, or "Спросить помощника" on Home): ask in plain
  Russian - "что у нас есть сладкого?", "есть безалкогольное пиво?", "сколько белка мне осталось?",
  "сколько потратили на рестораны в октябре?". Claude looks things up with read-only tools (stock,
  shopping list, food diary, weight, month finances, individual payments) and can add plain words
  ("milk", "eggs") to the shopping list - only after you say yes. One conversation per person, kept for 6 hours of quiet.
- One hourly cron runs it all; every message is sent once (`period_key`). To try one by hand:
  `env['family.ai.jobs'].run_now('protein' | 'forecast' | 'month', user_id)` in `odoo shell`.
- Messages are written in Russian by **Claude Haiku** (`claude-haiku-5-5`) from numbers the app
  computes itself, so the model never does the maths. Each of you only sees your own messages.
- The API key is read from `ANTHROPIC_API_KEY` (put it in `.env` next to `docker-compose.yml`).
  Without it the app keeps working and the assistant just stays quiet.

### Automatic weight sync (Zepp Life → Odoo)
1. Zepp Life syncs your weigh-ins to **Apple Health**.
2. An **iPhone Shortcut** reads the latest Health weight sample and POSTs it to
   `/gym/weight`, authenticated with a personal Odoo API key (`res.users.apikeys`, scope
   `family_scale`) — so the server knows *who* weighed in from the key alone.
3. It runs automatically via an **Automation**: "When Zepp Life is Closed → Run Shortcut".
4. Re-sending the same weigh-in is safe: the endpoint recognises it by timestamp and skips the
   duplicate instead of creating a second entry.

See [`weight_sync.py`](addons/family_gym/controllers/weight_sync.py) for the endpoint.

### Gym visits from the club Wi-Fi
The gym is inside a mall, so a location trigger would fire for the whole mall. Instead an iPhone
Shortcuts automation watches the club's Wi-Fi: *When I join it* → `POST /gym/visit {"event":"join"}`
(same personal API key as the weight sync). The first join of a day starts the visit; further joins
the same day change nothing. There is no "leave" automation: on a weak signal the phone drops off
the Wi-Fi again and again, so leaving was unreliable (the server ignores `"leave"` if an old
automation still sends it), and the visit length is not tracked. Green squares in Exercises light up by themselves.
See [`visit_sync.py`](addons/family_gym/controllers/visit_sync.py).

## Running it

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env   # optional, for family_ai
docker compose up -d --build
```

This starts Postgres and Odoo (`odoo:17.0` plus the `anthropic` package, see `Dockerfile`), with `addons/` mounted as extra addons and the
database `family_tracker_db`. First run: open `http://localhost:8069`, create the database, then
install **Family Daily Tracker** and **Family Gym & Fit** from Apps.

After changing any module code, upgrade it and restart:

```bash
docker compose exec odoo odoo -d family_tracker_db -u family_tracker,family_gym \
  --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --stop-after-init
docker compose restart odoo
```

### Phone access
Expose Odoo over HTTPS (e.g. `tailscale serve`) — the barcode scanner needs a secure context to
use the camera, and Safari is the only iOS browser that resolves a Tailscale MagicDNS name.
Open the site in Safari, then **Share → Add to Home Screen** for the "Family" app icon.

## What's not in this repo

- **Real data**: no database dump is committed. Bring your own via `docker compose up` and the
  Odoo installer, or restore a backup you keep outside the repo.
- **Secrets**: API keys, the Tailscale hostname and passwords live outside version control
  (`.gitignore` covers `.env`, `cookies.txt`, `*.sql.gz`).
