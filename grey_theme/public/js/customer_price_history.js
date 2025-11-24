frappe.provide("grey_theme.test");

frappe.ui.form.on("Sales Invoice Item", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        grey_theme.test.trigger_history_load(frm, row);
    },
    rate(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        grey_theme.test.updateHighlight(row);
    },
    sales_invoice_item_remove(frm, cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        grey_theme.test.hide(row);
    }
});

$.extend(grey_theme.test, {

    trigger_history_load(frm, row) {
        if (!frm.doc.customer || !row.item_code) return;

        if (row._history_timer) clearTimeout(row._history_timer);

        row._history_timer = setTimeout(() => {
            this.show(frm, row);
        }, 250);
    },

    show(frm, row) {
        frappe.call({
            method: "grey_theme.test.get_item_insights",
            args: {
                customer: frm.doc.customer,
                item_code: row.item_code,
                company: frm.doc.company,
                limit: 6,
                other_limit: 5
            },
            callback: (r) => {
                const data = r.message || {};
                grey_theme.test.render(frm, row, data);
            }
        });
    },

    render(frm, row, insights) {
        this.hide(row);

        const price_history = insights.price_history || [];
        const stock = insights.stock || [];
        const other_customers = insights.other_customers || [];
        const avg_rate = flt(insights.avg_rate || 0);
        const last_rate = flt(insights.last_rate || 0);

        const id = `si-price-assist-${row.name}`;
        const $box = $(`<div class="si-price-assist" id="${id}"></div>`).appendTo("body");

        $box.append(`
            <div class="pa-customer">${frm.doc.customer}</div>
        `);

        const $title = $(`
            <div class="pa-title">
                Price History: ${row.item_name || row.item_code}
            </div>
        `);
        $box.append($title);

        const current_rate = flt(row.rate);
        let diff_pct = null;
        let diff_text = "";
        let diff_class = "";

        if (current_rate && last_rate) {
            diff_pct = ((current_rate - last_rate) / last_rate) * 100;
            const absDiff = Math.abs(diff_pct);

            if (absDiff <= 5) {
                diff_class = "pa-price-good";
            } else if (absDiff <= 20) {
                diff_class = "pa-price-warn";
            } else {
                diff_class = "pa-price-bad";
            }

            diff_text = `${diff_pct >= 0 ? "+" : ""}${diff_pct.toFixed(1)}% vs last price`;
        }

        const $summary = $(`
            <div class="pa-summary ${diff_class}">
                <div class="pa-summary-main">
                    <div>
                        <label>Last</label>
                        <span>${last_rate ? last_rate : "-"}</span>
                    </div>
                    <div>
                        <label>Average</label>
                        <span>${avg_rate ? avg_rate.toFixed(2) : "-"}</span>
                    </div>
                    <div>
                        <label>Current</label>
                        <span>${current_rate || "-"}</span>
                    </div>
                </div>
                <div class="pa-summary-warning">
                    ${diff_text || ""}
                </div>
            </div>
        `);

        const sparkHtml = this.buildSparkline(price_history);
        if (sparkHtml) {
            $summary.append(sparkHtml);
        }
        $box.append($summary);

        for (let d of price_history) {
            const highlight = (flt(row.rate) === flt(d.rate));
            const baseLine = (d.base_rate && d.stock_uom && d.uom && d.uom !== d.stock_uom)
                ? `<small class="pa-uom">= ${d.base_rate} per ${d.stock_uom}</small>`
                : "";

            const $line = $(`
                <div class="pa-line ${highlight ? 'pa-match' : ''}">
                    <div class="pa-left">
                        <b>${d.rate}</b> (${d.currency}, ${d.uom})
                        <small>${d.qty} qty • ${frappe.format(d.posting_date, "Date")}</small>
                        ${baseLine}
                        <small class="pa-inv">
                            <a href="/app/sales-invoice/${encodeURIComponent(d.si)}" target="_blank">
                                ${d.si}
                            </a>
                        </small>
                    </div>
                    <button class="pa-use">Use</button>
                </div>
            `);

            $line.data("rate", d.rate);
            $box.append($line);
        }

        if (other_customers.length) {
            $box.append(`<div class="pa-section-title">Other customers paying</div>`);

            other_customers.forEach(d => {
                const $line = $(`
                    <div class="pa-line pa-other">
                        <div class="pa-left">
                            <b>${d.rate}</b> (${d.currency}, ${d.uom})
                            <small>${d.qty} qty • ${frappe.format(d.posting_date, "Date")}</small>
                            <small>${d.customer}</small>
                            <small class="pa-inv">
                                <a href="/app/sales-invoice/${encodeURIComponent(d.si)}" target="_blank">
                                    ${d.si}
                                </a>
                            </small>
                        </div>
                    </div>
                `);
                $box.append($line);
            });
        }

        if (stock.length) {
            $box.append(`<div class="pa-section-title">Stock by Warehouse</div>`);

            const recommended = stock[0];
            const maxProjected = flt(recommended.projected_qty || 0) || 1;

            for (let s of stock) {
                const canCover = flt(s.projected_qty) >= flt(row.qty);
                const fill = Math.min(100, (flt(s.projected_qty) / maxProjected) * 100);

                const $line = $(`
                    <div class="ps-line ${canCover ? 'ps-ok' : ''}">
                        <div class="ps-left">
                            <b>${s.warehouse}</b>
                            <small>${s.projected_qty} available</small>
                        </div>
                        <div class="ps-bar-wrap">
                            <div class="ps-bar" style="width:${fill}%;"></div>
                        </div>
                        <button class="ps-use">Use</button>
                    </div>
                `);
                $line.data("warehouse", s.warehouse);
                $box.append($line);
            }
        }

        const $input = $(
            `.grid-row[data-name="${row.name}"] input[data-fieldname="item_code"]`
        );

        if ($input.length) {
            const pos = $input.offset();
            $box.css({
                top: pos.top + $input.outerHeight() + 8,
                left: pos.left
            });
        }

        $box.on("click", ".pa-use", function () {
            const rate = $(this).closest(".pa-line").data("rate");
            if (rate != null) {
                frappe.model.set_value(row.doctype, row.name, "rate", rate);
                grey_theme.test.hide(row);
            }
        });

        $box.on("dblclick", ".pa-line", function () {
            const rate = $(this).data("rate");
            if (rate != null) {
                frappe.model.set_value(row.doctype, row.name, "rate", rate);
                grey_theme.test.hide(row);
            }
        });

        $box.on("click", ".ps-use", function () {
            const warehouse = $(this).closest(".ps-line").data("warehouse");
            if (warehouse) {
                frappe.model.set_value(row.doctype, row.name, "warehouse", warehouse);
            }
        });

        row._price_id = id;
        row._price_timeout = setTimeout(() => this.hide(row), 40000);
    },

    buildSparkline(history) {
        if (!history || !history.length) return "";

        const rates = history.map(d => flt(d.rate || 0));
        const max = Math.max(...rates);
        if (!max) return "";

        let html = '<div class="pa-sparkline"><div class="pa-sparkline-bars">';
        rates.forEach(r => {
            const height = 12 + (r / max) * 28;
            html += `<span style="height:${height}px"></span>`;
        });
        html += '</div><div class="pa-sparkline-label">Trend (last ' + history.length + ')</div></div>';
        return html;
    },

    updateHighlight(row) {
        if (!row || !row._price_id) return;

        const rate = flt(row.rate);

        $(`#${row._price_id} .pa-line`).each(function () {
            const saved_rate = flt($(this).data("rate"));
            $(this).toggleClass("pa-match", saved_rate === rate);
        });
    },

    hide(row) {
        if (!row) return;

        if (row._price_id) {
            $(`#${row._price_id}`).remove();
            delete row._price_id;
        }
        if (row._price_timeout) clearTimeout(row._price_timeout);
        if (row._history_timer) clearTimeout(row._history_timer);
    }
});

$(`<style>
.si-price-assist {
    position:absolute;
    z-index:1050;
    width:340px;
    background:#0d1117;
    color:white;
    padding:14px;
    border-radius:12px;
    box-shadow:0 8px 25px rgba(0,0,0,0.45);
    font-size:13px;
}

/* Customer + Title */
.pa-customer {
    font-size:12px;
    color:#c9d1d9;
    margin-bottom:4px;
    opacity:0.85;
}
.pa-title {
    font-weight:600;
    font-size:14px;
    margin-bottom:10px;
    opacity:0.9;
}

/* SUMMARY BLOCK */
.pa-summary {
    border-radius:10px;
    padding:10px 10px 8px;
    margin-bottom:10px;
    background:#111b24;
    border:1px solid rgba(255,255,255,0.06);
}
.pa-summary-main {
    display:flex;
    justify-content:space-between;
    gap:6px;
}
.pa-summary-main div label {
    display:block;
    font-size:10px;
    text-transform:uppercase;
    letter-spacing:0.5px;
    opacity:0.6;
}
.pa-summary-main div span {
    font-size:13px;
    font-weight:600;
}
.pa-summary-warning {
    margin-top:6px;
    font-size:11px;
    opacity:0.9;
}

/* Traffic light states */
.pa-price-good { border-color:rgba(0,200,120,0.4); }
.pa-price-good .pa-summary-warning { color:#00e676; }

.pa-price-warn { border-color:rgba(255,200,0,0.4); }
.pa-price-warn .pa-summary-warning { color:#ffeb3b; }

.pa-price-bad { border-color:rgba(255,80,80,0.5); }
.pa-price-bad .pa-summary-warning { color:#ff5252; }

/* Sparkline */
.pa-sparkline {
    margin-top:8px;
}
.pa-sparkline-bars {
    display:flex;
    align-items:flex-end;
    gap:4px;
    height:42px;
}
.pa-sparkline-bars span {
    display:block;
    width:6px;
    border-radius:999px;
    background:linear-gradient(180deg, #00d2ff, #3a7bd5);
    opacity:0.9;
}
.pa-sparkline-label {
    margin-top:2px;
    font-size:10px;
    opacity:0.65;
}

/* Section titles */
.pa-section-title {
    font-size:11px;
    text-transform:uppercase;
    letter-spacing:0.6px;
    opacity:0.7;
    margin:6px 0 4px;
}

/* PRICE LINES */
.pa-line {
    padding:10px;
    margin-bottom:8px;
    background:#111b24;
    border-radius:10px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    border:1px solid rgba(255,255,255,0.05);
    transition:0.2s ease;
}
.pa-line:hover {
    background:#16212c;
    border-color:rgba(0,180,255,0.25);
    cursor:pointer;
}
.pa-line.pa-match {
    border:1px solid rgba(0,255,200,0.35);
    box-shadow:0 0 8px rgba(0,255,200,0.25);
    background:#132d26;
}

/* Other customers look slightly dimmer */
.pa-line.pa-other {
    opacity:0.85;
}

/* Left text block */
.pa-left b {
    font-size:14px;
    font-weight:600;
}
.pa-left small {
    display:block;
    font-size:10px;
    opacity:0.75;
    margin-top:2px;
}
.pa-uom {
    font-size:10px;
    opacity:0.7;
}
.pa-inv a {
    color:#9fb9ff;
    text-decoration:none;
    font-size:10px;
}
.pa-inv a:hover {
    text-decoration:underline;
}

/* USE button */
.pa-use {
    padding:6px 14px;
    font-size:11px;
    border-radius:8px;
    border:none;
    background:linear-gradient(90deg, #00d2ff, #3a7bd5);
    color:white;
    font-weight:600;
    cursor:pointer;
    transition:0.2s ease;
    box-shadow:0 2px 6px rgba(0,150,255,0.3);
}
.pa-use:hover {
    transform:scale(1.07);
    opacity:1;
}
.pa-use:active {
    transform:scale(0.95);
}

/* STOCK LINES */
.ps-line {
    padding:8px;
    margin-bottom:6px;
    background:#101820;
    border-radius:10px;
    display:flex;
    align-items:center;
    gap:8px;
    border:1px solid rgba(255,255,255,0.06);
}
.ps-line.ps-ok {
    border-color:rgba(0,255,120,0.4);
    box-shadow:0 0 6px rgba(0,255,120,0.25);
}
.ps-left {
    min-width:120px;
}
.ps-left b {
    font-size:12px;
}
.ps-left small {
    display:block;
    font-size:10px;
    opacity:0.75;
}
.ps-bar-wrap {
    flex:1;
    height:6px;
    background:rgba(255,255,255,0.06);
    border-radius:999px;
    overflow:hidden;
}
.ps-bar {
    height:6px;
    border-radius:999px;
    background:linear-gradient(90deg,#00e676,#00b0ff);
}

/* STOCK Use button */
.ps-use {
    padding:4px 10px;
    font-size:10px;
    border-radius:999px;
    border:none;
    background:#263238;
    color:#e0f7fa;
    cursor:pointer;
    transition:0.15s ease;
}
.ps-use:hover {
    background:#37474f;
}
</style>`).appendTo("head");
