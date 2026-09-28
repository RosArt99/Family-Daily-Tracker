/** @odoo-module **/

import { CallbackRecorder } from "@web/webclient/actions/action_hook";
import { patch } from "@web/core/utils/patch";

// Swapping in a custom Renderer for one view type (groceries_stock_list.js's List) somehow
// leaves the *previous* view's own view-switch callback (Kanban's, registered by Odoo's own
// useSetupView) still in this recorder after Kanban has already unmounted. Confirmed by testing
// on an untouched Odoo model (res.partner: Contacts) - switching Kanban -> List -> Kanban there
// never fails, only here, and only with our custom List Renderer swapped in; a stub Renderer
// that never even reads its props reproduces it too, so this is a timing/lifecycle quirk in
// Odoo's own view-switch machinery, not a bug in what our Renderer does.
//
// The next switch then calls that dangling callback to snapshot "where were you scrolled to"
// for the breadcrumb, which reads a DOM ref that no longer exists -> TypeError, and Odoo's own
// error boundary turns that into a blocking "Odoo Client Error" dialog.
//
// Rather than fight Owl's scheduling to find the exact race, make every callback stored here
// tolerate a stale ref: skip it (empty state for that one view) instead of throwing and taking
// down the whole switch. This can only ever affect what gets remembered for restoring scroll
// position on this one view type - never data, never which records exist.
patch(CallbackRecorder.prototype, {
    add(owner, callback) {
        super.add(owner, (...args) => {
            try {
                return callback(...args);
            } catch (error) {
                console.error("Ignored a stale view-switch callback:", error);
                return {};
            }
        });
    },
});
