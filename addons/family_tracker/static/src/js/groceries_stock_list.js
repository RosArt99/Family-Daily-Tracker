/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { withSort } from "./groceries_stock_sort";
import { Component } from "@odoo/owl";

// What the "List" tab of Shopping List & Stock shows: same physical packs Kanban shows one
// card per item, but the state-lifecycle Kanban is for browsing "how much of this do we
// actually have" - so this rolls identical product+status rows into one card with a summed
// quantity (the whole reason for this file), in the same look as Open Food Facts' own list.
//
// It only replaces the Renderer of the stock ListView; Model/Controller/ArchParser (search,
// filters, sorting, the "New" button, record fetching) are untouched, so this stays a normal
// Odoo list underneath - it just draws different DOM from the same fetched records.
const STATE_META = {
    to_buy: { label: _t("To Buy"), icon: "fa-shopping-cart", action: "in_stock" },
    in_stock: { label: _t("In Stock"), icon: "fa-check-circle", action: "consumed" },
    consumed: { label: _t("Consumed / Discarded"), icon: "fa-trash-o", action: null },
};
const STATE_ORDER = ["to_buy", "in_stock", "consumed"];
const ACTION_LABEL = { in_stock: _t("Mark all Purchased"), consumed: _t("Mark all Consumed") };
const ACTION_METHOD = { in_stock: "action_mark_purchased", consumed: "action_mark_consumed" };
const ACTION_PAST = { in_stock: _t("purchased"), consumed: _t("consumed") };

export class GroceriesStockListRenderer extends Component {
    static template = "family_tracker.GroceriesStockList";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
    }

    // Recomputed every render straight from the (reactive) fetched records, so it always
    // reflects the active search/filters exactly like the native table would.
    get groups() {
        const byKey = new Map();
        for (const record of this.props.list.records) {
            const d = record.data;
            const productId = d.product_id ? d.product_id[0] : 0;
            const key = productId + "|" + d.state;
            let group = byKey.get(key);
            if (!group) {
                group = {
                    key,
                    productId,
                    productName: d.product_id ? d.product_id[1] : _t("Unknown product"),
                    state: d.state,
                    quantity: 0,
                    count: 0,
                    uomName: d.uom_id ? d.uom_id[1] : "",
                    isEssential: d.is_essential,
                    nutriscore: d.nutriscore_grade,
                    autoRestock: d.auto_restock,
                    entryIds: [],
                };
                byKey.set(key, group);
            }
            group.quantity += d.quantity || 0;
            group.count += 1;
            group.entryIds.push(record.resId);
        }
        const groups = [...byKey.values()];
        // Records arrive from the server already ordered (the Sort button changes the model's
        // orderBy). Sorting by name is ours to do; for dates the Map above already holds the
        // groups in order of first appearance, i.e. newest first.
        const orderBy = this.props.list.orderBy;
        const byName = !orderBy.length || orderBy[0].name === "product_id";
        return byName ? groups.sort((a, b) => a.productName.localeCompare(b.productName)) : groups;
    }

    get sections() {
        const groups = this.groups;
        return STATE_ORDER.map((state) => ({
            state,
            ...STATE_META[state],
            items: groups.filter((group) => group.state === state),
        })).filter((section) => section.items.length);
    }

    get isEmpty() {
        return !this.props.list.records.length;
    }

    // Only worth telling apart from the quantity itself for loose-weight items (3 packs of
    // 2.5 kg -> "7.5 kg (3 packs)"); packaged items are 1 pack = 1 unit, so "6 (6 packs)"
    // would just repeat the same number.
    showCountHint(group) {
        return group.count > 1 && group.quantity !== group.count;
    }

    qty(group) {
        // Whole numbers show as "9", loose weights keep one decimal ("2.5").
        const rounded = Math.round(group.quantity * 10) / 10;
        return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
    }

    imageUrl(group) {
        return `/web/image/groceries.product/${group.productId}/image/128x128`;
    }

    openProduct(group) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: group.productName,
            res_model: "groceries.product",
            res_id: group.productId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onToggleRestock(ev, group) {
        ev.stopPropagation();
        await this.orm.call("groceries.product", "action_toggle_restock", [[group.productId]]);
        await this.props.list.model.load();
    }

    // "Buy Again" on a Consumed card: one tap, one fresh To Buy entry for that product - no
    // confirmation needed, it only ever adds, same as scanning "Add to shopping list" would.
    async onBuyAgain(ev, group) {
        ev.stopPropagation();
        await this.orm.call("groceries.product", "action_add_to_shopping_list", [[group.productId]]);
        await this.props.list.model.load();
    }

    onGroupAction(ev, group) {
        ev.stopPropagation();
        const action = STATE_META[group.state].action;
        this.dialog.add(ConfirmationDialog, {
            title: ACTION_LABEL[action],
            body:
                group.count > 1
                    ? _t("Mark all %s packs of %s (%s %s) as %s?", group.count, group.productName,
                         this.qty(group), group.uomName, ACTION_PAST[action])
                    : _t("Mark %s as %s?", group.productName, ACTION_PAST[action]),
            confirmLabel: ACTION_LABEL[action],
            confirm: async () => {
                await this.orm.call("groceries.stock_entry", ACTION_METHOD[action], [group.entryIds]);
                await this.props.list.model.load();
            },
            cancel: () => {},
        });
    }
}

export const groceriesStockListView = {
    ...listView,
    Renderer: GroceriesStockListRenderer,
    Controller: withSort(ListController, "family_tracker.StockListView"),
    buttonTemplate: "family_tracker.GroceriesStockList.Buttons",
};

registry.category("views").add("groceries_stock_list", groceriesStockListView);
