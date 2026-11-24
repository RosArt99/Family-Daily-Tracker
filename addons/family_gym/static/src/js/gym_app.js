/** @odoo-module **/

import { registry } from "@web/core/registry";

// Registers Gym & Fit with the shared family shell (theme colours, Home tile, phone tab bar).
registry.category("family_apps").add(
    "gym",
    {
        key: "gym",
        menuXmlid: "family_gym.menu_gym_root",
        icon: "fa-heartbeat",
        color: "#c41e3f",
        pattern: "/family_gym/static/src/img/navbar_pattern_gym.png?v=2",
        modelPrefix: "gym.",
        description: "Exercises, weight & meals",
        tabs: [
            { xmlid: "family_gym.menu_gym_meals", icon: "fa-cutlery" },
            { xmlid: "family_gym.menu_gym_weight", icon: "fa-balance-scale", svg: "/family_gym/static/src/img/icons/scale.svg" },
            { xmlid: "family_gym.menu_gym_exercises", icon: "fa-line-chart", svg: "/family_gym/static/src/img/icons/dumbbell.svg" },
        ],
    },
    { sequence: 30 }
);

// Recipes: a Home tile of their own (screen in recipes_screen.js).
registry.category("family_apps").add(
    "recipes",
    {
        key: "recipes",
        menuXmlid: "family_gym.menu_recipes_root",
        icon: "fa-book",
        color: "#D2691E",
        pattern: "/family_gym/static/src/img/navbar_pattern_gym.png?v=2",
        description: "Your dishes - tap to add to the diary",
        tabs: [],
    },
    { sequence: 25 }
);
