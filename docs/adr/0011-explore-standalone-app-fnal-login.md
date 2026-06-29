# Extract the FD-VD explorer into a standalone, FNAL-login app

status: accepted

The `/hwdb/explore/` view ([[0010-fd-vd-component-dashboard-over-hwdb-hierarchy]])
grows into a standalone site — **DUNE Hardware Explorer** — for all DUNE
hardware, not only CE. It becomes its own Django app `explore` mounted at
top-level `/explore/`, with its own chrome, and its **own login: the FNAL
device flow is the sole credential**. A normal user authenticates only with
FNAL, sees a generic hardware tree, and never touches the CE tooling. This
deliberately **relaxes the "purely additive" constraint of ADR-0010** — that
constraint governed the original additive feature; consolidating it into a
proper site is the follow-on, and is allowed to move code and change auth.

## Context

ADR-0010 shipped the explorer as an additive view inside the CE-centric `hwdb`
app, gated by the project-wide Django login (a shared `guest` account) with the
FNAL link as a separate, optional layer used only to mint bearers. DUNE
management wants the explorer to read as its own product for the whole detector,
and wants access gated by FNAL identity rather than the shared `guest` password.
The `~/Code/dunecat` hub already validates the shape we want — OIDC device-flow
completion provisions a user keyed on a stable identity (`oidc_sub`) — but on a
bespoke FastAPI/Vue stack with raw-sqlite session tables. cets is Django +
server-rendered templates + htmx, and already owns the same vault device flow in
`hwdb/fnal/`.

## Decision

- **New app `explore`, top-level `/explore/`.** Same project/deployment (one
  gunicorn service — see deployment memory), own `base.html`, nav, and branding.
  Permanent redirects from `/hwdb/explore/*`. Server-rendered + htmx, **not** a
  Vue/Vite SPA.
- **FNAL device flow is the sole login.** On completion of an explore-started
  flow, `get_or_create` a Django user and `login()` them (Strategy 1 — real
  Django users, not session-only). This is dunecat's `upsert_user(oidc_sub)`
  pattern expressed on Django's user system; we keep cets's existing
  `hwdb/fnal/` flow and do **not** port dunecat's session/user tables or its
  stack. Extends [[0001-session-scoped-fnal-linkage]] and
  [[0002-per-request-bearer-minting]] — the session vault token is unchanged;
  we additionally bind a Django identity to it for the explore app.
- **FNAL users live in a `fnal:<credkey>` username namespace**, disjoint from
  local accounts — *not* the bare `credkey`. Keying on the bare credkey would
  merge the FNAL identity space with local usernames: a FNAL login whose credkey
  matched a pre-existing account (e.g. the `admin` superuser, or a CE teammate
  enrolled in `cets`) would resolve to *that* account, silently granting CETS
  access — a privilege-escalation path and the reason "logging in via FNAL as
  chaoz still showed CETS" during dev. With the namespace, signing in via FNAL
  is always a distinct, group-less → explore-only identity; CETS staff reach the
  CETS zone through their password login (and, being `cets` members, see explore
  too — no FNAL link needed). The colon is rejected by Django's username
  validator, so no hand-created account can collide with the namespace.
- **One shared device flow, two intents.** The flow carries a `login_user` flag
  set at *start*: explore-started flows auto-login; the CE "Link FNAL" flow
  (CETS zone) stays link-only and **byte-for-byte unchanged** — a `guest`
  linking FNAL to upload is never swapped into a `credkey` user. The shared
  `fnal/flow.py`/`bearer.py`/`crypto.py` primitives are untouched; only the
  start/complete views differ per app.
- **Two access zones, deny-by-default.** Membership is the Django group `cets`
  (a data migration adds existing accounts; FNAL auto-provisioned users get no
  group). One middleware after `AuthenticationMiddleware`: a non-`cets`,
  non-superuser user may touch only explore + the FNAL flow + logout + admin +
  static; any other path → 403. No CETS view is edited — the rule lives in one
  place. `is_staff` alone does **not** grant CETS; superuser bypasses.
- **View vs sync gating.** Viewing explore needs only authentication (CETS
  members enter without a FNAL link; unauthenticated → FNAL login). A **live
  FNAL link is required only for live HWDB sync**, for both user classes — the
  existing `mint_for` → relink path, unchanged.
- **Code move, clean tables.** Move to `explore`: the four mirror models
  (`ComponentTypeNode`, `HwdbTestEvent`, `HwdbComponentEvent`,
  `HierarchySyncState`), `hierarchy.py`, `events.py`, the explore views/urls/
  template, and the explore chart helpers (`component_type_progress`,
  `component_update_progress`; generic `chart_config` stays in `core`). The
  shared HWDB gateway stays in `hwdb`: `fnal/`, `api_client.py`, `instance.py`,
  `context_processors.py`, plus all CE consumers. New `explore_*` tables are
  created and the old `hwdb_*` mirror tables dropped — the mirror is a
  disposable cache, rebuilt by re-sync (no data migration; cf.
  [[0007-hwdb-mirror-separation]]).
- **Visual identity from dunecat.** Port dunecat's `tokens.css` + `base.css`
  design system (cream/amber, IBM Plex) and re-skin its chrome
  (header/page-frame/buttons) as plain CSS + Django templates — distinct from
  CETS's Geist look, reinforcing "its own site."
- **CE is a generic node.** FD CE (system 81) appears as just another system in
  the tree with the generic plots; the CE deep-links (`_ce_links` → larasic /
  dashboard) are dropped entirely. A normal user notices no CE-specific parts.
- **Scope: FD-VD whitelist unchanged.** This reorg is structural, not a content
  expansion. FD-HD and PDS are future, gated on probing where PDS lands among
  the HWDB systems; widening `is_fdvd_system` is a one-line edit when DUNE asks.

## Consequences

- The project-wide "any login sees everything" assumption is gone: there are now
  two authorization zones. A future third zone must be classified deliberately
  (the guard denies CETS by default), not silently exposed.
- A re-sync is needed on the twister deploy after the table move (hierarchy is
  seconds; visited leaves re-pull lazily).
- Two login surfaces coexist (password for CETS, FNAL for explore) driven off
  one global `LOGIN_URL`; the explore guard issues its own redirect rather than
  relying on that setting.
- ADR-0010's additive constraint no longer holds for this code; the explorer's
  models and logic now live in `explore`, imported gateway code in `hwdb`.
