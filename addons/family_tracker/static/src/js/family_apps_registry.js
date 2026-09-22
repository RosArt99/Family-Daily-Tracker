/** @odoo-module **/

import { registry } from "@web/core/registry";

const apps = registry.category("family_apps");

// Home is the landing page: the phone bottom bar's "Home" button opens it, and it lists
// every other registered app as a tile.
apps.add(
    "home",
    {
        key: "home",
        isHome: true,
        showBottomNav: false,
        menuXmlid: "family_tracker.menu_home_root",
        icon: "fa-home",
        color: "#3B4A54",
        pattern: "/family_tracker/static/src/img/navbar_pattern_home.png",
    },
    { sequence: 1 }
);

apps.add(
    "groceries",
    {
        key: "groceries",
        menuXmlid: "family_tracker.menu_groceries_root",
        icon: "fa-shopping-basket",
        color: "#347136",
        pattern: "/family_tracker/static/src/img/navbar_pattern.png",
        modelPrefix: "groceries.",
        description: "Shopping list, stock & barcodes",
        tabs: [
            { xmlid: "family_tracker.menu_groceries_scan", icon: "fa-barcode" },
            { xmlid: "family_tracker.menu_groceries_shopping", icon: "fa-shopping-basket" },
            { xmlid: "family_tracker.menu_groceries_products", icon: "fa-th-large" },
        ],
    },
    { sequence: 20 }
);
