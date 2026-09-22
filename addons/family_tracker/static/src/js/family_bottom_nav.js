/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";
import { currentFamilyApp, familyApps } from "./family_apps";

// Phone-only tab bar shared by all family apps: a Home button on the left followed by the
// current app's own tabs (taken from its registry entry). Odoo hides the top section menu
// below the `md` breakpoint, so this puts the same menus within thumb reach. Phone vs
// desktop visibility is pure CSS (family_theme.scss); it renders nothing outside family apps
// and on the Home page itself.
class FamilyBottomNav extends Component {
    setup() {
        this.menuService = useService("menu");
        this.actionService = useService("action");
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.render());
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.render());
    }

    get tabs() {
        const app = currentFamilyApp(this.menuService);
        if (!app || app.showBottomNav === false) {
            return [];
        }
        const menus = this.menuService.getAll();
        const controller = this.actionService.currentController;
        const activeActionId = controller && controller.action && controller.action.id;
        const tabs = [];
        const homeApp = familyApps.getAll().find((a) => a.isHome);
        const homeMenu = homeApp && menus.find((m) => m.xmlid === homeApp.menuXmlid);
        if (homeMenu) {
            tabs.push({ xmlid: "home", icon: homeApp.icon, menu: homeMenu, active: false });
        }
        for (const tab of app.tabs || []) {
            const menu = menus.find((m) => m.xmlid === tab.xmlid);
            if (menu) {
                tabs.push({ ...tab, menu, active: menu.actionID === activeActionId });
            }
        }
        return tabs;
    }

    onTabClick(menu) {
        this.menuService.selectMenu(menu);
    }
}

FamilyBottomNav.template = "family_tracker.FamilyBottomNav";
FamilyBottomNav.props = {};

registry.category("main_components").add("FamilyBottomNav", {
    Component: FamilyBottomNav,
});
