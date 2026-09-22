/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { familyApps } from "./family_apps";

// Odoo tries to save a modified record when you navigate away. For a NEW record that still
// lacks a required field (e.g. a stock entry without a product) the save is refused with an
// "Invalid fields" notification and you cannot leave the form until you find the Discard
// button - very easy to get stuck on a phone. In our own models, walking away from a new
// record that cannot be saved yet simply means abandoning it, so discard it and go on.
// A new record that IS valid is still saved on leave, exactly as before.
patch(FormController.prototype, {
    async beforeLeave() {
        const record = this.model.root;
        if (
            record.isNew &&
            record.dirty &&
            !this.allowLeavingWithoutSaving &&
            familyApps.getAll().some((a) => a.modelPrefix && record.resModel.startsWith(a.modelPrefix)) &&
            !record._checkValidity({ silent: true })
        ) {
            await record.discard();
            return;
        }
        return super.beforeLeave(...arguments);
    },
});
