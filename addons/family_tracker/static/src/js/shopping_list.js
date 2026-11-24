/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { BarcodeScanDialog } from "./barcode_scan_dialog";

const MODEL = "groceries.shopping_list";

// The Shopping List: a plain checklist meant to replace a note on the phone. Type or scan to
// add, tap a line in the store to tick it off (= bought, it goes In Stock), tap a ticked line
// to take it back. Packs scanned In Stock anywhere else drop off this list by themselves.
export class ShoppingList extends Component {
    static template = "family_tracker.ShoppingList";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.rpc = useService("rpc");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.inputRef = useRef("input");
        this.state = useState({
            toBuy: [],
            bought: [],
            query: "",
            suggestions: [],
            busy: false,
            showBought: true,
        });
        this.searchTimer = null;
        onWillStart(() => this.load());
    }

    apply(data) {
        this.state.toBuy = data.to_buy;
        this.state.bought = data.bought;
    }

    async load() {
        this.apply(await this.orm.call(MODEL, "get_list", []));
    }

    async call(method, args) {
        this.state.busy = true;
        try {
            this.apply(await this.orm.call(MODEL, method, args));
        } finally {
            this.state.busy = false;
        }
    }

    // ---- sections: food first, then household things, like walking through a store
    get groups() {
        const food = this.state.toBuy.filter((l) => l.is_food);
        const home = this.state.toBuy.filter((l) => !l.is_food);
        const groups = [];
        if (food.length) {
            groups.push({ key: "food", title: home.length ? "Еда" : "", lines: food });
        }
        if (home.length) {
            groups.push({ key: "home", title: "Для дома", lines: home });
        }
        return groups;
    }

    get total() {
        return this.state.toBuy.reduce((sum, line) => sum + line.count, 0);
    }

    imageUrl(line) {
        return `/web/image/groceries.product/${line.product_id}/image/128`;
    }

    // ---- adding
    onInput(ev) {
        this.state.query = ev.target.value;
        clearTimeout(this.searchTimer);
        const query = this.state.query.trim();
        if (query.length < 2) {
            this.state.suggestions = [];
            return;
        }
        this.searchTimer = setTimeout(async () => {
            const found = await this.orm.call(MODEL, "search_products", [query]);
            if (this.state.query.trim() === query) {
                this.state.suggestions = found;
            }
        }, 250);
    }

    get exactMatch() {
        const query = this.state.query.trim().toLowerCase();
        return this.state.suggestions.some((s) => s.name.toLowerCase() === query);
    }

    clearInput() {
        this.state.query = "";
        this.state.suggestions = [];
        if (this.inputRef.el) {
            this.inputRef.el.value = "";
        }
    }

    async addProduct(product) {
        this.clearInput();
        await this.call("add", [product.id]);
    }

    async addTyped() {
        const name = this.state.query.trim();
        if (!name) {
            return;
        }
        this.clearInput();
        await this.call("add", [false, name]);
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.addTyped();
        }
    }

    scan() {
        this.dialog.add(BarcodeScanDialog, {
            title: "Добавить в список",
            onScan: async (barcode) => {
                const result = await this.rpc("/groceries/scan", { barcode, action: "to_buy" });
                if (result.error) {
                    this.notification.add(result.error, { type: "danger" });
                    return;
                }
                this.notification.add(`В списке: ${result.product_name}`, { type: "success" });
                await this.load();
            },
        });
    }

    // ---- in the store
    check(line) {
        // Feels instant: move the line first, then let the server confirm.
        this.state.toBuy = this.state.toBuy.filter((l) => l !== line);
        this.state.bought = [line, ...this.state.bought];
        return this.call("check", [line.entry_ids]);
    }

    uncheck(line) {
        return this.call("uncheck", [line.entry_ids]);
    }

    plus(line) {
        return this.call("change_count", [line.product_id, 1]);
    }

    minus(line) {
        return this.call("change_count", [line.product_id, -1]);
    }

    remove(line) {
        return this.call("remove", [line.product_id]);
    }

    toggleBought() {
        this.state.showBought = !this.state.showBought;
    }
}

registry.category("actions").add("family_tracker.shopping_list", ShoppingList);
