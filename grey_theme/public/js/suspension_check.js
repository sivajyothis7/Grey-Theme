;(function () {
    const path = window.location.pathname || "";
    const allow = ["/login", "/suspended"];
    if (allow.some(p => path.startsWith(p))) return;

    const checkAndRedirect = () => {
        if (!(window.frappe && frappe.call)) return;
        frappe.call({
            method: "grey_theme.suspension_api.is_site_suspended",
            freeze: false,
            callback: function (r) {
                const msg = r && r.message;
                if (msg && msg.is_suspended && msg.user !== "Administrator") {
                    window.location.replace("/suspended");
                }
            }
        });
    };

    window.addEventListener("load", function () {
        checkAndRedirect();
        let attempts = 0;
        const t = setInterval(() => {
            attempts += 1;
            checkAndRedirect();
            if (attempts > 5) clearInterval(t);
        }, 1000);
    });

    const attachRealtime = () => {
        if (!(window.frappe && frappe.realtime && frappe.realtime.on)) return;
        if (window.__suspension_rt_bound) return;
        window.__suspension_rt_bound = true;
        frappe.realtime.on("site_suspension_update", function () {
            checkAndRedirect();
            const pathNow = window.location.pathname || "";
            if (pathNow.startsWith("/suspended")) {
                frappe.call({
                    method: "grey_theme.suspension_api.is_site_suspended",
                    freeze: false,
                    callback: function (r) {
                        const msg = r && r.message;
                        if (msg && !msg.is_suspended) {
                            window.location.replace("/login");
                        }
                    }
                });
            }
        });
    };
    window.addEventListener("load", function () {
        let tries = 0;
        const it = setInterval(() => {
            tries += 1;
            attachRealtime();
            if (tries > 10 || window.__suspension_rt_bound) clearInterval(it);
        }, 500);
    });
})();

