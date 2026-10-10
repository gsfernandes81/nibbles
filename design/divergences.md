# Divergences from the design

Every place the build differs from `design.md` or the mockups, waiting for the
owner to approve it or send it back. One entry per divergence, newest last:

```
## <screen or rule> — <date>

- Spec: what design.md or the mockup says.
- Built: what was built instead.
- Why: what made the spec impossible or worse in practice.
- Status: awaiting approval | approved <date> | sent back <date>
```

## More tab and window card — the budget source settings — 2026-10-10

- Spec: section 5 lists the More tab's rows (window, reserve, auto, skip
  codecs, quality chips, destinations, nightly job, runner log, quit) and the
  Queue tab's window card draws "what the next window may spend against what
  expires". Neither knows about a budget source, because there was none.
- Built: the runner now has three more settings in `expire_runner.SETTINGS` —
  `budget` (zwana | manual), `allowance` (MB a day, "not set" at 0) and `reset`
  (a time of day; stored UTC, spelled on the phone's clock by
  `spell_setting`). Under a manual budget `snapshot()["expiring"]` is `None`:
  nothing can say what expires when the rest of the phone's use is not
  counted. The old curses settings page (`b`, `l`, `t`) shows and sets them,
  and shows only the settings that apply to the budget source
  (`expire_runner.settings_shown`): `allowance` and `reset` under manual,
  `reserve-when-paid` and `paid-min` under zwana. Below 16 rows it gives up the
  blank under its title, so all its rows fit at 40×14. The rebuilt screens are
  not touched.
- Approved for the rebuild (owner, 2026-10-10, over side-by-side sketches):
  - **More:** `b budget` as a switch row under `reserve` (`◉ manual`), with
    `l allowance` and `t reset` under it, shown only while the budget is
    manual, as `paid-min` shows only under the waiver. `allowance` opens the
    number sheet (presets `500 MB 1 GB 2 GB 5 GB`); `reset` opens a time sheet
    on the phone's clock. A change says itself on the line above the tabs
    (`allowance is 1.5 GB a day`).
  - **Window card, manual budget:** the bar draws `spendable` against
    `allowance.left_bytes`, and the figure keeps the spec's own shape,
    `1017/1144 MiB to spend` (22 columns, all there is beside Run now). Never
    "expires". Keyboard up, the strip reads `waiting · 1017/1144 MiB`.
  - **Window card, no allowance set:** `no daily allowance set` where the
    verdict would be, `set it under More` under it, and Run now drawn off. The
    status bar reads `WAITING  no allowance set`.
  - The Now sheet's red "on mobile data, charged" case never applies to a
    manual budget: what it spends is counted against the allowance either way.
- Why: a manual budget has figures the spec has no place for, and one figure
  (what expires) it cannot have at all. The first wording proposed for the
  card, `480 MiB of 1.2 GiB left to spend`, was 32 columns and did not fit.
- Status: approved 2026-10-10
