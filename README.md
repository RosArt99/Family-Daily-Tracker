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
- **Shopping list & stock**, kanban or list, with low-stock and essentials tracking.
- The **shared shell** every other module plugs into: theme colours, the phone bottom tab bar,
  the Home page, and the PWA (`Add to Home Screen` on iPhone gives you a real app icon, no
  Safari chrome).

### `family_gym` — Gym & Fit
- **Weight**: log it by hand, or let the scale do it (see below). The graph shows both of you
  on one line each, zoomed to your actual range — not flattened against a 0 axis.
- **Exercises**: pick an exercise (or type a new one to create it), log a row per set — weight
  on the left, reps on the right — and the graph tracks your heaviest set of each session.
- **Calendar**: workouts by day/type, with exercises and sets logged right inside.
- **Meals**: a food diary (breakfast/lunch/dinner/snacks) with calories and macros pulled from
  the product catalog.
- **Goals**: personal targets per person.

### Automatic weight sync (Zepp Life → Odoo)
1. Zepp Life syncs your weigh-ins to **Apple Health**.
2. An **iPhone Shortcut** reads the latest Health weight sample and POSTs it to
   `/gym/weight`, authenticated with a personal Odoo API key (`res.users.apikeys`, scope
   `family_scale`) — so the server knows *who* weighed in from the key alone.
3. It runs automatically via an **Automation**: "When Zepp Life is Closed → Run Shortcut".
4. Re-sending the same weigh-in is safe: the endpoint recognises it by timestamp and skips the
   duplicate instead of creating a second entry.

See [`weight_sync.py`](addons/family_gym/controllers/weight_sync.py) for the endpoint.

## Running it

```bash
docker compose up -d
```

This starts Postgres and Odoo (`odoo:17.0`), with `addons/` mounted as extra addons and the
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
