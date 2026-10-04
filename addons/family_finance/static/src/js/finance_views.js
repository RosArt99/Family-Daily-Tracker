/** @odoo-module **/

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { FinanceEntryDialog, KIND_BY_MODEL } from "./finance_dialogs";

// "New" and a tap on a card/row open the friendly Finance dialog (finance_dialogs.js) instead of
// Odoo's plain form - for every Finance model that has one. Plans are the exception for editing:
// a plan has a budget table and savings, which the full form handles better than a dialog.
const EDIT_IN_DIALOG = new Set(["bill", "housing", "income", "saving"]);

function withFinanceDialogs(Controller) {
    return class extends Controller {
        setup() {
            super.setup();
            this.financeDialogs = useService("dialog");
        }

        get financeKind() {
            return KIND_BY_MODEL[this.props.resModel];
        }

        async financeReload() {
            await this.model.root.load();
            this.render(true);
        }

        openFinanceDialog(props) {
            this.financeDialogs.add(FinanceEntryDialog, {
                kind: this.financeKind,
                onSaved: () => this.financeReload(),
                ...props,
            });
        }

        async createRecord() {
            if (this.financeKind) {
                this.openFinanceDialog({});
                return;
            }
            return super.createRecord(...arguments);
        }

        async openRecord(record) {
            if (EDIT_IN_DIALOG.has(this.financeKind)) {
                this.openFinanceDialog({ resId: record.resId });
                return;
            }
            return super.openRecord(...arguments);
        }
    };
}

registry.category("views").add("finance_kanban", {
    ...kanbanView,
    Controller: withFinanceDialogs(KanbanController),
});

registry.category("views").add("finance_list", {
    ...listView,
    Controller: withFinanceDialogs(ListController),
});
