/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { BarcodeScanDialog } from "./barcode_scan_dialog";

const MODEL = "groceries.shopping_list";

// The Shopping List: a plain checklist meant to replace a note on the phone. Lines are plain
// words ("milk", "garlic") - in the store you take whichever milk is there - or, when scanned,
// a specific product. Tapping a line strikes it through in place (for a scanned product that
// also means bought: it goes In Stock); tap again to undo. "Clear ticked" tidies up.
export class ShoppingList extends Component {
    static template = "family_tracker.ShoppingList";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.rpc = useService("rpc");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.inputRef = useRef("input");
        this.state = useState({ lines: [], sections: [], query: "", suggestions: [], moving: null });
        this.searchTimer = null;
        onWillStart(() => this.load());
    }

    apply(data) {
        this.state.lines = data.lines;
        this.state.sections = data.sections;
    }

    async load() {
        this.apply(await this.orm.call(MODEL, "get_list", []));
    }

    async call(method, args) {
        this.apply(await this.orm.call(MODEL, method, args));
    }

    // Lines come sorted by store section (the way through the store); show a title per section.
    get groups() {
        const names = Object.fromEntries(this.state.sections.map((s) => [s.id, s.name]));
        const groups = [];
        for (const line of this.state.lines) {
            let group = groups[groups.length - 1];
            if (!group || group.id !== line.section_id) {
                group = { id: line.section_id, name: names[line.section_id] || "", lines: [] };
                groups.push(group);
            }
            group.lines.push(line);
        }
        return groups;
    }

    // ---- moving a line to another section (remembered for that word next time)
    openMove(line) {
        this.state.moving = line;
    }

    closeMove() {
        this.state.moving = null;
    }

    async moveTo(section) {
        const line = this.state.moving;
        this.state.moving = null;
        await this.call("set_section", [line.kind, line.id, section.id]);
    }

    async removeMoving() {
        const line = this.state.moving;
        this.state.moving = null;
        await this.call("remove", [line.kind, line.id]);
    }

    get left() {
        return this.state.lines.filter((l) => !l.done).length;
    }

    get doneCount() {
        return this.state.lines.filter((l) => l.done).length;
    }

    imageUrl(line) {
        return `/web/image/groceries.product/${line.product_id}/image/128`;
    }

    // ---- adding plain words
    onInput(ev) {
        this.state.query = ev.target.value;
        clearTimeout(this.searchTimer);
        const query = this.state.query.trim();
        if (!query) {
            this.state.suggestions = [];
            return;
        }
        this.searchTimer = setTimeout(async () => {
            const found = await this.orm.call(MODEL, "suggest", [query]);
            if (this.state.query.trim() === query) {
                this.state.suggestions = found.filter((name) => name.toLowerCase() !== query.toLowerCase());
            }
        }, 200);
    }

    clearInput() {
        this.state.query = "";
        this.state.suggestions = [];
        if (this.inputRef.el) {
            this.inputRef.el.value = "";
        }
    }

    async add(name) {
        name = (name ?? this.state.query).trim();
        if (!name) {
            return;
        }
        this.clearInput();
        await this.call("add_item", [name]);
        // Keep the keyboard up: usually several things are typed in a row.
        if (this.inputRef.el) {
            this.inputRef.el.focus();
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.add();
        }
    }

    // ---- adding a specific product
    scan() {
        this.dialog.add(BarcodeScanDialog, {
            title: "Add to the list",
            onScan: async (barcode) => {
                const result = await this.rpc("/groceries/scan", { barcode, action: "to_buy" });
                if (result.error) {
                    this.notification.add(result.error, { type: "danger" });
                    return;
                }
                this.notification.add(`Added: ${result.product_name}`, { type: "success" });
                await this.load();
            },
        });
    }

    // ---- in the store
    toggle(line) {
        line.done = !line.done; // strike it through right away, the server confirms
        return this.call("toggle", [line.kind, line.id, line.entry_ids || []]);
    }

    plus(line) {
        return this.call("change_count", [line.kind, line.id, 1]);
    }

    minus(line) {
        return this.call("change_count", [line.kind, line.id, -1]);
    }

    clearDone() {
        return this.call("clear_done", []);
    }
}

registry.category("actions").add("family_tracker.shopping_list", ShoppingList);
