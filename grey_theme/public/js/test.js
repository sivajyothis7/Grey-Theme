frappe.provide("grey_theme.test");

frappe.ui.form.on("Sales Order Item", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;
        if (row._assist_timer) clearTimeout(row._assist_timer);
        row._assist_timer = setTimeout(() => {
            grey_theme.test.show(frm, row);
        }, 250);
    },
    qty(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        grey_theme.test.updateSparkle(row);
    },
    sales_order_item_remove(frm, cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        grey_theme.test.hide(row);
    }
});

$.extend(grey_theme.test, {
    show(frm, row) {
        frappe.call({
            method: "grey_theme.test.get_item_warehouse_stock",
            args: {
                item_code: row.item_code,
                company: frm.doc.company,
                limit: 6
            },
            callback(r) {
                const data = r.message || [];
                grey_theme.test.render(frm, row, data);
            }
        });
    },

    render(frm, row, data) {
        this.hide(row);
        const id = `stock-assist-${row.name}`;
        const $box = $(`<div class="stock-assist" id="${id}"></div>`).appendTo("body");

        const $title = $(`<div class="sa-title">${row.item_name || row.item_code}</div>`);
        $box.append($title);

        let recommended = data.length ? data[0] : null;
        for (let wh of data) {
            const canCover = (flt(wh.projected_qty) >= flt(row.qty));
            const fill = Math.min(100, (wh.projected_qty / (recommended.projected_qty || 1)) * 100);
            const $line = $(`
                <div class="sa-line ${canCover ? 'sa-spark' : ''}">
                    <div class="sa-left">
                        <b>${wh.warehouse}</b>
                        <small>${wh.projected_qty}</small>
                    </div>
                    <div class="sa-bar-wrap"><div class="sa-bar" style="width:${fill}%"></div></div>
                    <button class="btn btn-xs sa-use">Use</button>
                </div>
            `);
            $line.data("warehouse", wh.warehouse);
            $box.append($line);
        }

        if (recommended) {
            $(`<div class="sa-banner">Recommend: ${recommended.warehouse} (${recommended.projected_qty})</div>`).appendTo($box);
        }

        const $input = $(`.grid-row[data-name="${row.name}"] input[data-fieldname="item_code"]`);
        if ($input.length) {
            const pos = $input.offset();
            $box.css({ top: pos.top + $input.outerHeight() + 8, left: pos.left });
        }

        $box.on("click", ".sa-use", function() {
            const warehouse = $(this).closest(".sa-line").data("warehouse");
            frappe.model.set_value(row.doctype, row.name, "warehouse", warehouse);
            grey_theme.test.hide(row);
        });

        row._assist_id = id;
        row._assist_timeout = setTimeout(() => grey_theme.test.hide(row), 40000);
    },

    updateSparkle(row) {
        if (!row || !row._assist_id) return;
        const qty = flt(row.qty);
        $(`#${row._assist_id} .sa-line`).each(function() {
            const txt = $(this).find("small").text();
            const stock = flt(txt);
            $(this).toggleClass("sa-spark", stock >= qty && qty > 0);
        });
    },

    hide(row) {
        if (!row) return;
        if (row._assist_id) {
            $(`#${row._assist_id}`).remove();
            delete row._assist_id;
        }
        if (row._assist_timeout) clearTimeout(row._assist_timeout);
        if (row._assist_timer) clearTimeout(row._assist_timer);
    }
});

// CSS styling
$(`<style>
.stock-assist {
    position: absolute;
    z-index: 1050;
    width: 280px;
    background: #111a22;
    color: white;
    padding: 8px;
    border-radius: 8px;
    box-shadow: 0 8px 25px rgba(0,0,0,0.4);
    font-size: 12px;
}
.stock-assist .sa-title { font-weight: 600; margin-bottom: 6px; }
.stock-assist .sa-line { display:flex; align-items:center; gap:8px; margin-bottom:4px; background:rgba(255,255,255,0.05); padding:5px; border-radius:5px; }
.stock-assist .sa-line.sa-spark { box-shadow: 0 0 8px rgba(0,255,120,0.3); border:1px solid rgba(0,255,120,0.15); }
.stock-assist .sa-left { width:130px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.stock-assist .sa-bar-wrap { flex:1; height:6px; background:rgba(255,255,255,0.05); border-radius:3px; overflow:hidden; }
.stock-assist .sa-bar { height:6px; background:linear-gradient(90deg, #00e676, #00b0ff); border-radius:3px; }
.stock-assist .sa-banner { margin-top:5px; font-size:11px; color:#a0ffb0; text-align:center; }
</style>`).appendTo("head");
