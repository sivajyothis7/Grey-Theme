## Grey Theme App

Grey Theme

## Features

Two optional desk UI enhancements, both driven by a single settings page —
**Grey Theme UI Settings** (Single DocType, module *Grey Theme*). Both are off by
default; with the switches off the desk is stock Frappe.

**Grid Enhancer** — child tables (the Items grid on a Sales Invoice, etc.) render
the columns Frappe would drop past its 11-unit budget, sized by Frappe's own
proportions scaled to the container. Once those widths no longer fit — a narrow
window, a Split View pane, browser zoom — the grid scrolls horizontally with the
heading and filter rows locked to the body, and columns pinned from
*Configure Columns* stay at the left edge.

**Split View** — a list view gains a *Split View* entry in its views menu: list on
the left, the selected document's form on the right, with a draggable splitter
whose width is remembered in that browser's local storage. DocTypes can be
excluded from it.

Full settings reference, install/upgrade steps, and the manual QA checklist:
[docs/ui-features.md](docs/ui-features.md).

#### License

mit
