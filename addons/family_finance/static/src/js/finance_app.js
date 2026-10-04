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
        description: "Bills, rent, income, savings & plans",
        tabs: [
            { xmlid: "family_finance.menu_finance_overview", icon: "fa-pie-chart" },
            { xmlid: "family_finance.menu_finance_bills", icon: "fa-shopping-basket" },
            { xmlid: "family_finance.menu_finance_housing", icon: "fa-home" },
            { xmlid: "family_finance.menu_finance_income", icon: "fa-money" },
            { xmlid: "family_finance.menu_finance_savings", icon: "fa-university" },
            { xmlid: "family_finance.menu_finance_plans", icon: "fa-plane" },
        ],
    },
    { sequence: 40 }
);
