/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

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
        this.state = useState({ search: "", inStockOnly: true, products: [], selected: [] });
        this.searchDebounced = useDebounced(() => this.load(), 250);
        onWillStart(() => this.load());
    }

    get title() {
        return this.props.title || _t("Choose food");
    }

    async load() {
        const domain = [];
        if (this.state.search.trim()) {
            domain.push(["name", "ilike", this.state.search.trim()]);
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
