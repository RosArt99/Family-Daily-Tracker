/** @odoo-module **/

import { registry } from "@web/core/registry";
import { THEME_VARS, currentFamilyApp, themeVars } from "./family_apps";

const BODY_CLASS = "o_family_theme";
const DEFAULT_COLOR = "#3B4A54";

// Odoo has no per-app theming. Whenever the active app changes we put its colours on <body>
// as CSS variables (family_theme.scss reads them), so each family app gets its own look.
export const familyThemeService = {
    dependencies: ["menu"],
    start(env, { menu }) {
        const apply = () => {
            const app = currentFamilyApp(menu);
            const body = document.body;
            body.classList.toggle(BODY_CLASS, !!app);
            const vars = app ? themeVars(app) : {};
            for (const name of THEME_VARS) {
                if (name in vars) {
                    body.style.setProperty(name, vars[name]);
                } else {
                    body.style.removeProperty(name);
                }
            }
            const meta = document.querySelector('meta[name="theme-color"]');
            if (meta) {
                meta.setAttribute("content", app ? app.color : DEFAULT_COLOR);
            }
        };
        env.bus.addEventListener("MENUS:APP-CHANGED", apply);
        apply();
    },
};

registry.category("services").add("family_theme", familyThemeService);
