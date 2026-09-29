# Grey Theme — Desk UI Features

Grey Theme ships two optional desk enhancements. Both are off until you turn them
on, and both are driven by a single settings page:

**Settings DocType:** `Grey Theme UI Settings` (Single, module *Grey Theme*).
Open it from the awesomebar: type *Grey Theme UI Settings*.

The settings are published into the desk at boot as `frappe.boot.grey_theme_ui`,
and every piece of JS and CSS in these features is gated on it. With both master
switches off, the desk is stock Frappe.

---

## 1. Grid Enhancer

Frappe renders a child table (the Items grid on a Sales Invoice, the rows on a
Stock Entry, and so on) into a fixed 11-column-unit row. Once the eligible
in-list-view fields exceed that budget, the remaining columns are simply dropped
from the row — you have to open each row to see them.

Grid Enhancer changes that:

- Columns that stock Frappe would **drop** past its 11-unit budget are rendered.
- Column widths are **computed**: Frappe's own N/12 proportion is resolved against
  the live container and floored at `grid_min_column_width`. On a wide screen the
  proportion wins and the grid fills the container exactly as stock does.
- The grid scrolls **horizontally** once those widths no longer fit — a narrow
  window, a Split View pane, browser zoom, or simply a lot of columns. A child
  table that fits does not scroll, and does not need to.
- The **heading row and the filter/search row scroll with the body**, so column
  headers stay aligned with their data.
- Columns can be **pinned (sticky)** to the left from the *Configure Columns*
  dialog, so the key identifying column stays visible while you scroll right.
  The pinned set is saved with the rest of your column layout.

### Settings

| Field | What it controls |
|---|---|
| `enable_grid_enhancer` | Master switch. Unticked = feature completely inert. |
| `grid_column_limit` | Total column units rendered per grid row. Stock Frappe caps this at 11; raise it to render more columns. Note the renderer reserves 1 unit internally, so the *Configure Columns* dialog accepts totals up to `grid_column_limit - 1`. |
| `grid_min_column_width` | The per-unit floor, in pixels. A column `N` units wide never renders narrower than `N + 1` halves of this (a 1-unit column ≥ 1x, a 3-unit column ≥ 2x). Raising it makes grids reach their scrolling threshold sooner. |
| `grid_sticky_columns` | Allow pinning columns from *Configure Columns*. |
| `grid_max_sticky_columns` | How many columns a user may pin at once. |

Sticky columns must be **contiguous from the left** — you cannot pin the 1st and
the 4th column and leave a gap. Breaking either that rule or the maximum raises a
validation message in the *Configure Columns* dialog.

A **single** column may still be at most 20 units wide, even though the total
budget is much higher. Frappe stamps each cell with a `col-xs-<width>` class and
the stylesheet only emits width rules up to 20; a wider column would render
unsized and pull the heading, filter and data rows out of alignment. Exceeding it
raises a validation message.

> **Note on the naming.** The form fields are `enable_grid_enhancer` /
> `enable_split_view`; the keys published to the browser in
> `frappe.boot.grey_theme_ui` are the shorter `grid_enhancer` / `split_view`.
> Every other field keeps the same name in both places.

---

## 2. Split View

Split View adds a **Split View** entry to a list view's *views* menu. That menu is
itself governed by the **View Switcher** desk setting: on a role where it is
turned off the dropdown does not exist, and Split View has no entry point. Reach
it by route in that case — `/app/split_view/<DocType>`. Choosing it
puts the list in a narrow left pane and the selected document's form in a right
pane, so you can walk a list of documents without bouncing back and forth through
the router.

- Clicking a row loads that document into the right pane. You can edit and save
  there exactly as on the full form.
- The divider between the panes is **draggable**, and there is a reset control to
  put it back to the configured default.
- The width you drag to **persists** for you across reloads.
- Row checkboxes still behave as checkboxes — ticking one selects the row for a
  bulk action instead of loading the form.

### Settings

| Field | What it controls |
|---|---|
| `enable_split_view` | Master switch. Unticked = the menu entry never appears. |
| `split_view_list_width_pct` | Default width of the list pane, as a percentage of the available width. |
| `split_view_min_pane_width` | Minimum width of either pane, in pixels. The splitter will not drag past it. |
| `split_view_hide_page_from_search` | Hide the Split View page itself from awesomebar results, so it does not clutter search. |
| `split_view_excluded_doctypes` | DocTypes that should never offer Split View (heavy forms, single-purpose lists). |

---

## Install / upgrade

```bash
# first install
cd ~/frappe-bench
bench get-app https://github.com/sivajyothis7/Grey-Theme.git
bench --site <site> install-app grey_theme

# upgrade an existing install
cd ~/frappe-bench/apps/grey_theme
git pull

# either way, finish with:
cd ~/frappe-bench
bench --site <site> migrate
bench build --app grey_theme
bench --site <site> clear-cache
bench restart
```

### Why `clear-cache` matters

The settings do not travel with each request — they are baked into **bootinfo**,
the JSON blob the desk receives once at page load, and Frappe caches bootinfo
**per user**. If you change a value in *Grey Theme UI Settings* and skip
`clear-cache`, every user who already has a cached boot keeps the old flags until
their cache expires, and the change looks like it did nothing. Clear the cache,
then hard-reload the browser (Cmd/Ctrl + Shift + R) so the rebuilt asset bundle is
fetched too.

Order matters: `migrate` first (it installs/updates the DocType), then `build`
(it compiles the JS/CSS bundle), then `clear-cache`, then `restart`.

---

## Manual QA checklist

Run this after any install, upgrade, or Frappe version bump.

### Grid Enhancer

1. Tick **Enable Grid Enhancer** in *Grey Theme UI Settings*, save,
   `bench --site <site> clear-cache`, hard-reload the desk.
2. Open a **Sales Invoice** (new or existing) and look at the Items table.
   Confirm columns that stock Frappe dropped are now rendered, and that the grid
   still **fills** the container with no gap on the right.
2b. **Narrow the browser window** (or open the same form in Split View) until the
   per-column floors bind. Confirm the grid gains a horizontal scrollbar rather
   than squeezing the columns. A grid that fits is *supposed* not to scroll.
3. Scroll the grid right. Confirm the **heading row** and the **filter/search
   row** move in lockstep with the data rows — no drift, no misaligned headers.
4. Open *Configure Columns* on that grid and **pin two columns**. Save. Narrow the
   window until the grid scrolls, then confirm the pinned columns stay put while
   the rest scrolls under them. (Pinning has no visible effect while the grid
   still fits — there is nothing to scroll.)
5. **Reload the page.** Confirm the pinned columns are still pinned (the state is
   saved in your GridView user setting).
6. In *Configure Columns*, try to pin a column that is **not contiguous from the
   left** (e.g. pin column 1 and column 4). Confirm an error about sticky columns
   needing to start at the left edge is raised and the dialog does not save.
7. Try to pin **more than `grid_max_sticky_columns`**. Confirm an error naming
   that maximum is raised.
8. Scroll the grid right, then **expand a row** (the pencil / *Edit* control).
   Confirm the row form opens correctly and is not clipped or offset.
9. Add enough rows to exceed one page (**more than 50**). Confirm the grid
   pagination control appears and pages through the rows correctly.
10. On a DocType whose child table sets **`grid_page_length`** in its meta,
    confirm that value is still honoured (Grey Theme must not override it).

### Split View

11. Tick **Enable Split View**, save, `clear-cache`, hard-reload.
12. Open any list view (e.g. Sales Invoice list). Open the **views menu** and
    confirm a **Split View** entry is present. Choose it.
13. **Click a row.** Confirm the document loads into the right pane.
14. **Edit a field and save** in the right pane. Confirm the save succeeds and the
    left-hand list reflects the change.
15. **Drag the splitter.** Confirm both panes resize and neither collapses past
    `split_view_min_pane_width`.
16. Hit **reset**. Confirm the split returns to `split_view_list_width_pct`.
17. Drag to a new width, then **reload**. Confirm the width you chose persisted.
18. **Tick a row checkbox.** Confirm it toggles the checkbox (and the bulk-action
    bar) instead of loading that document into the right pane.
19. Add a DocType to `split_view_excluded_doctypes`, save, `clear-cache`,
    hard-reload. Confirm that DocType's list view **does not** offer Split View.
20. If `split_view_hide_page_from_search` is on, type *Split* into the awesomebar
    and confirm the Split View page is not offered as a result.

### Off-switch (run this last — it is the important one)

21. Untick **both** *Enable Grid Enhancer* and *Enable Split View*. Save.
22. `bench --site <site> clear-cache`, then hard-reload the desk.
23. Confirm the grid and list views are **byte-identical to stock Frappe**:
    - no horizontal scrollbar on child tables, no pin controls in
      *Configure Columns*;
    - no Split View entry in any views menu;
    - `document.body` carries **neither** `grey-ui-grid` **nor** `grey-ui-split`
      (check in devtools, or run `document.body.className` in the console);
    - the browser console is **clean** — no errors, no warnings from Grey Theme.

---

## How this differs from the upstream apps

These features are ports of two community apps, but the implementation is
deliberately different.

**We do not vendor Frappe's grid files.** The upstream `grid_enhancer` app works
by shipping its own fork of `grid.js`, `grid_row.js`, `grid_pagination.js` and
`grid_row_form.js`, taken from an older v15 revision. Diffing that fork against
current `version-15` shows it silently **reverts** upstream fixes that have landed
since, including:

- identity-based row matching in `render_result_rows` (the old copy matches by
  index, which mis-assigns rows after a delete);
- `get_random_name()` row naming (the old copy names rows `"row " + idx`);
- `grid_page_length` meta support;
- optional-chaining guards added upstream to stop null dereferences;
- the 5000-row cap on CSV import into a grid;
- `depends_on` dependency refresh on the row form;
- `toggle_editable_row` on add.

Grey Theme instead applies thin, **idempotent runtime patches** over whichever
Frappe version is actually installed. It reaches the live `Grid` and `GridRow`
classes through `frappe.ui.form.ControlTable` (the only supported entry point —
`Grid` and `GridRow` are ES-module default exports, not globals), calls `super`,
and wraps the methods it needs. Upstream fixes are preserved, and a Frappe upgrade
does not silently roll the grid back.

**We dropped Split-View's vendored jQuery resizable plugin** and the
`web_include_js` hook that loaded it on every website page. The splitter is
implemented directly; nothing is injected into the public website.

---

## Known limits

- **Frappe v15 only.** The patches target v15 grid internals (`setup_visible_columns`,
  `make_column`, the *Configure Columns* dialog chain). v16 restructures these —
  re-verify before upgrading a site that relies on these features.
- **Sticky columns are stored per user**, inside the `GridView` user setting for
  that DocType (`frappe.model.user_settings`). They are not a company-wide layout:
  each user pins their own columns, and clearing a user's settings clears the pins.
- **Desk only.** Neither feature touches the website, portal pages, or web forms.
- **Pinning engages only when the grid scrolls.** On a wide screen a child table
  that fits shows no scrollbar, so a pinned column looks no different. It takes
  effect as soon as the container narrows.
- **Split View does not live-update.** Its list deliberately does not subscribe to
  realtime, because frappe keeps a single global `list_update` handler and
  subscribing would take it away from the user's own list view.
- Changing settings needs a `clear-cache` plus a hard reload before users see it —
  see *Why `clear-cache` matters* above.
