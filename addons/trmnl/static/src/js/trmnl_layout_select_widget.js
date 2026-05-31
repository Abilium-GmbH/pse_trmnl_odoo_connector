/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import {
    SelectionField,
    selectionField,
} from "@web/views/fields/selection/selection_field";

/**
 * TrmnlLayoutSelectField — a SelectionField that filters its options live.
 *
 * The parent class reads `record.fields[name].selection` which is cached from
 * fields_get() and always contains all three values (list/kanban/calendar).
 * This subclass narrows that list to what `available_view_types` reports for
 * the currently selected Odoo Model, so the dropdown only shows valid choices.
 *
 * `available_view_types` is a computed Char field (e.g. "list,kanban") that
 * Odoo re-sends on every onchange when app_model_id changes, so OWL's
 * reactivity keeps this widget in sync automatically.
 */
class TrmnlLayoutSelectField extends SelectionField {
    get options() {
        const allOptions = this.props.record.fields[this.props.name].selection.filter(
            ([, label]) => label !== ""
        );
        const rawAvailable = this.props.record.data.available_view_types || "";
        const available = rawAvailable
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);

        // No model selected (field is invisible in this state, but guard
        // defensively so the widget is never broken if visibility changes).
        if (!available.length) {
            return allOptions;
        }

        return allOptions.filter(([value]) => available.includes(value));
    }

    // Guard: if the stored value was reset by onchange but the widget renders
    // before the update propagates, avoid a thrown error in the parent's string
    // getter (which does options.find(...))[1] without a null check).
    get string() {
        const value = this.props.record.data[this.props.name];
        if (value === false || value === null) {
            return "";
        }
        const found = this.options.find(([v]) => v === value);
        return found ? found[1] : "";
    }
}

registry.category("fields").add("trmnl_layout_select", {
    ...selectionField,
    component: TrmnlLayoutSelectField,
    displayName: _t("TRMNL Layout Select"),
    supportedTypes: ["selection"],
});
