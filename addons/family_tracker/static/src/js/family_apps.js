/** @odoo-module **/

import { registry } from "@web/core/registry";

// Every family app (Home, Groceries, Gym & Fit, ...) registers itself here from its own addon:
//   registry.category("family_apps").add("gym", { menuXmlid, color, pattern, icon, tabs, ... },
//                                        { sequence: 30 });
// The theme service, the phone bottom bar and the Home page are all driven by this registry,
// so adding an app never means touching the shared code.
export const familyApps = registry.category("family_apps");

export function currentFamilyApp(menuService) {
    const app = menuService.getCurrentApp();
    return app ? familyApps.getAll().find((a) => a.menuXmlid === app.xmlid) : undefined;
}

// --- colour helpers: derive the darker shades the SCSS needs from the app's base colour ---

function hexToRgb(hex) {
    const n = parseInt(hex.replace("#", ""), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHsl([r, g, b]) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0;
    const l = (max + min) / 2;
    if (max !== min) {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        if (max === r) { h = (g - b) / d + (g < b ? 6 : 0); }
        else if (max === g) { h = (b - r) / d + 2; }
        else { h = (r - g) / d + 4; }
        h /= 6;
    }
    return [h, s, l];
}

function hslToHex([h, s, l]) {
    const hue = (p, q, t) => {
        if (t < 0) { t += 1; }
        if (t > 1) { t -= 1; }
        if (t < 1 / 6) { return p + (q - p) * 6 * t; }
        if (t < 1 / 2) { return q; }
        if (t < 2 / 3) { return p + (q - p) * (2 / 3 - t) * 6; }
        return p;
    };
    let r, g, b;
    if (s === 0) { r = g = b = l; }
    else {
        const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
        const p = 2 * l - q;
        r = hue(p, q, h + 1 / 3); g = hue(p, q, h); b = hue(p, q, h - 1 / 3);
    }
    return "#" + [r, g, b].map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join("");
}

// Same as Sass darken(hex, amount): lower HSL lightness by `amount` (0..1).
export function darken(hex, amount) {
    const [h, s, l] = rgbToHsl(hexToRgb(hex));
    return hslToHex([h, s, Math.max(0, l - amount)]);
}

export const THEME_VARS = ["--fam-color", "--fam-color-dark", "--fam-color-darker", "--fam-rgb", "--fam-pattern"];

export function themeVars(app) {
    return {
        "--fam-color": app.color,
        "--fam-color-dark": darken(app.color, 0.08),
        "--fam-color-darker": darken(app.color, 0.12),
        "--fam-rgb": hexToRgb(app.color).join(", "),
        "--fam-pattern": app.pattern ? `url("${app.pattern}")` : "none",
    };
}
