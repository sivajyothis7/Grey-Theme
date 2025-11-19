frappe.ui.form.on('Site Suspension Settings', {
    refresh: function(frm) {
        if (frm.doc.is_suspended) {
            frm.add_custom_button(__('Activate Site'), function() {
                frm.set_value('is_suspended', 0);
                frm.save();
            }).addClass('btn-success');
        } else {
            frm.add_custom_button(__('Suspend Site'), function() {
                frm.set_value('is_suspended', 1);
                frm.save();
            }).addClass('btn-danger');
        }
    }
});
