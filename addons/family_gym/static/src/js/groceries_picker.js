/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { BarcodeScanDialog } from "@family_tracker/js/barcode_scan_dialog";

// A product picker styled like Shopping List & Stock's List cards (same o_gs_card classes from
// family_tracker, so it also inherits whichever app's theme colour is active) instead of the
// plain Odoo record table - used wherever a food gets chosen from the Groceries catalog: the
// diary's "From Groceries" and a recipe's "Add ingredient". Shows kcal/100g per product, which
// is the thing you actually want to see while picking what to eat (the stock cards never
// needed it).
export class GroceriesPickerDialog extends Component {
    static template = "family_gym.GroceriesPickerDialog";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        multiSelect: { type: Boolean, optional: true },
        onSelected: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ search: "", inStockOnly: true, products: [], selected: [] });
        this.searchDebounced = useDebounced(() => this.load(), 250);
        onWillStart(() => this.load());
    }

    get title() {
        return this.props.title || _t("Choose food");
    }

    async load() {
        // Household items (cleaning supplies, toilet paper, ...) never belong in a meal -
        // hard-excluded, not a toggle, since there's no legitimate reason to see them here.
        const domain = [["is_food", "=", true]];
        if (this.state.search.trim()) {
            // Typed digits find a product by barcode too, not only by name.
            domain.push("|", ["name", "ilike", this.state.search.trim()], ["barcode", "=", this.state.search.trim()]);
        }
        if (this.state.inStockOnly) {
            domain.push(["stock_quantity", ">", 0]);
        }
        this.state.products = await this.orm.searchRead(
            "groceries.product",
            domain,
            ["name", "is_essential", "nutriscore_grade", "energy_kcal_100g", "stock_quantity"],
            { order: "name", limit: 60 }
        );
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.searchDebounced();
    }

    // The camera finds the pack in your hand, so it does not matter whether the product is
    // "in stock" - a scanned product is picked straight away.
    scanBarcode() {
        this.dialog.add(BarcodeScanDialog, { onScan: (barcode) => this.onScanned(barcode) });
    }

    async onScanned(barcode) {
        const [product] = await this.orm.searchRead(
            "groceries.product", [["barcode", "=", barcode]], ["name", "is_food"], { limit: 1 }
        );
        if (!product) {
            this.notification.add(_t("No product with barcode %s in Groceries yet.", barcode), { type: "warning" });
            return;
        }
        if (!product.is_food) {
            this.notification.add(_t("%s is not a food product.", product.name), { type: "warning" });
            return;
        }
        if (!this.props.multiSelect) {
            this.props.onSelected([product.id]);
            this.props.close();
            return;
        }
        // Several products can be ticked: tick this one and show it in the list.
        if (!this.state.selected.includes(product.id)) {
            this.state.selected = [...this.state.selected, product.id];
        }
        this.state.search = product.name;
        this.state.inStockOnly = false;
        await this.load();
    }

    toggleInStock() {
        this.state.inStockOnly = !this.state.inStockOnly;
        this.load();
    }

    imageUrl(product) {
        return `/web/image/groceries.product/${product.id}/image/128x128`;
    }

    kcal(product) {
        return Math.round(product.energy_kcal_100g);
    }

    isSelected(product) {
        return this.state.selected.includes(product.id);
    }

    onPick(product) {
        if (!this.props.multiSelect) {
            this.props.onSelected([product.id]);
            this.props.close();
            return;
        }
        this.state.selected = this.isSelected(product)
            ? this.state.selected.filter((id) => id !== product.id)
            : [...this.state.selected, product.id];
    }

    confirm() {
        this.props.onSelected(this.state.selected);
        this.props.close();
    }
}
