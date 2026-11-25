/** @odoo-module **/

import { registry } from "@web/core/registry";

// Registers Finance with the shared family shell (theme colours, Home tile, phone tab bar).
registry.category("family_apps").add(
    "finance",
    {
        key: "finance",
        menuXmlid: "family_finance.menu_finance_root",
        icon: "fa-money",
        image: "/family_finance/static/src/img/finance_logo.png",
        color: "#4194c8",
        pattern: "/family_finance/static/src/img/navbar_pattern_finance.png",
        modelPrefix: "finance.",
        description: "Expenses, income & crypto",
        tabs: [
            { xmlid: "family_finance.menu_finance_overview", icon: "fa-pie-chart" },
            { xmlid: "family_finance.menu_finance_expenses", icon: "fa-shopping-basket" },
            { xmlid: "family_finance.menu_finance_income", icon: "fa-money" },
            { xmlid: "family_finance.menu_finance_crypto", icon: "fa-btc" },
        ],
    },
    { sequence: 40 }
);

// Crypto as its own Home tile (the same screen as the Finance > Crypto tab), in Binance yellow.
registry.category("family_apps").add(
    "crypto",
    {
        key: "crypto",
        menuXmlid: "family_finance.menu_crypto_root",
        icon: "fa-btc",
        color: "#F0B90B",
        pattern: "/family_finance/static/src/img/navbar_pattern_finance.png",
        description: "BTC, ETH, XRP - value and profit",
        tabs: [],
    },
    { sequence: 45 }
);
