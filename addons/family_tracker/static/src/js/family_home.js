/** @odoo-module **/

import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";
import { familyApps } from "./family_apps";

// Landing page: one big tile per registered family app.
class FamilyHome extends Component {
    setup() {
        this.menuService = useService("menu");
        this.userName = ((session && session.name) || "").split(" ")[0];
    }

    get apps() {
        const menus = this.menuService.getAll();
        return familyApps
            .getAll()
            .filter((app) => !app.isHome)
            .map((app) => ({ ...app, menu: menus.find((m) => m.xmlid === app.menuXmlid) }))
            .filter((app) => app.menu);
    }

    tileStyle(app) {
        return `--tile-color: ${app.color};`;
    }

    open(app) {
        this.menuService.selectMenu(app.menu);
    }
}

FamilyHome.template = "family_tracker.FamilyHome";
FamilyHome.props = ["*"];

registry.category("actions").add("family_tracker.home", FamilyHome);
