"""TRMNL profile — domain evaluation and filter preset logic.

Extracted from ``trmnl_profile`` as a focused ``_inherit`` mixin, following the
same pattern used throughout the device model split (lifecycle, security,
telemetry, display, UI).

Responsibilities
----------------
- Safe-eval of the user-supplied ``filter_domain`` string.
- Structural validation of domain leaves at save time (``_check_filter_domain``).
- Semantic validation of domain field names at render time
  (``_validate_custom_domain_fields``).
- Preset filter domain building (``_build_filter_domain``).
- Combining preset + custom domains into one ORM domain
  (``_build_effective_domain``).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

_DOMAIN_BOOL_OPS = frozenset(("&", "|", "!"))

# Priority-ordered list of date/datetime fields used by filter_preset.
# create_date is the guaranteed fallback — it exists on every Odoo model.
_FILTER_DATE_FIELDS = ["date_deadline", "date_order", "start", "date", "create_date"]


class TrmnlProfileDomainMixin(models.Model):
    """Domain evaluation, filter preset building, and save-time constrains."""

    _inherit = "trmnl.profile"

    # ------------------------------------------------------------------
    # domain / filter helpers
    # ------------------------------------------------------------------

    def _eval_filter_domain(self, domain_str):
        """Evaluate a domain string using safe_eval with a restricted Odoo context.

        Returns a plain list suitable for use in ``search()``.
        Raises ``ValueError`` on syntax/type errors so callers can wrap it in
        whatever exception type is appropriate for their context.
        """
        if not domain_str or domain_str.strip() in ("", "[]"):
            return []
        profile_user = self.user_ids[:1] or self.env.user
        eval_ctx = {
            "uid": profile_user.id,
            "user": profile_user,
            "context_today": lambda: fields.Date.today(),
            "current_date": str(fields.Date.today()),
            "True": True,
            "False": False,
            "None": None,
        }
        result = safe_eval(domain_str, eval_ctx)
        if not isinstance(result, list):
            raise ValueError(_("Domain must evaluate to a list, got %s.") % type(result).__name__)
        return result

    def _validate_custom_domain_fields(self, domain, model_name):
        """Raise UserError if any domain leaf references a field absent from model_name.

        This is the render-time semantic complement to _validate_domain_leaves()
        (which is the save-time structural check). Structural validity is checked at
        save time; model-field existence is only knowable at render time once we have
        a concrete model_name.

        Only the first segment of dotted paths is checked (e.g. 'partner_id' of
        'partner_id.name'), since ORM traversal handles the rest.
        """
        if model_name not in self.env:
            return
        model_fields = self.env[model_name]._fields
        for token in domain:
            # Must test str before "token in _DOMAIN_BOOL_OPS" — list leaves are unhashable.
            if isinstance(token, str) and token in _DOMAIN_BOOL_OPS:
                continue
            if not isinstance(token, (list, tuple)) or len(token) != 3:
                continue
            field_path = token[0]
            if not isinstance(field_path, str):
                continue
            first_field = field_path.split(".")[0]
            if first_field not in model_fields:
                raise UserError(
                    _("Custom Domain references unknown field '%s' on model '%s'. "
                      "Please correct or clear the Custom Filter.")
                    % (first_field, model_name)
                )

    def _build_effective_domain(self, model_name):
        """Combine all active domain sources into a single ORM domain list.

        Sources applied with AND in this order:
        1. Filter preset  — from _build_filter_domain(); always silent.
        2. Custom domain  — from filter_domain; raises UserError on eval/field error.
        """
        domains = []

        # 1. Filter preset domain
        preset_domain = self._build_filter_domain(model_name)
        if preset_domain:
            domains.append(preset_domain)

        # 2. Custom filter_domain — eval errors and unknown fields both raise UserError.
        raw_custom = (self.filter_domain or "").strip()
        if raw_custom and raw_custom != "[]":
            try:
                custom_domain = self._eval_filter_domain(raw_custom)
                if custom_domain:
                    custom_domain = self._normalize_domain_m2o_values(custom_domain)
                    self._validate_custom_domain_fields(custom_domain, model_name)
                    domains.append(custom_domain)
            except UserError:
                raise
            except Exception as exc:
                raise UserError(
                    _("Custom Domain is invalid and could not be applied: %s") % exc
                ) from exc

        return list(Domain.AND(domains)) if domains else []

    @staticmethod
    def _normalize_domain_m2o_values(domain):
        """Replace [id, "display_name"] many2one pairs in domain values with plain id.

        Odoo's domain widget serialises many2one equality values as a 2-element
        list [id, label].  That representation is accepted by our validator but
        rejected by the ORM's search() which expects a bare integer.  Walk every
        leaf and flatten any such pair so the domain is ORM-safe.
        """
        normalized = []
        for token in domain:
            if isinstance(token, str) and token in _DOMAIN_BOOL_OPS:
                normalized.append(token)
            elif isinstance(token, (list, tuple)) and len(token) == 3:
                field_path, op, value = token
                if (
                    isinstance(value, (list, tuple))
                    and len(value) == 2
                    and isinstance(value[0], int)
                    and isinstance(value[1], str)
                ):
                    value = value[0]
                normalized.append((field_path, op, value))
            else:
                normalized.append(token)
        return normalized

    @staticmethod
    def _validate_domain_leaves(domain):
        """Raise ValueError if any leaf is not a valid 3-element (field, op, value) tuple.

        Domain.AND() in Odoo 19 validates structure but this method also catches
        inputs like [('a', 'b')] (2-tuple) at save time rather than producing a
        cryptic database error at render/search time.
        """
        for token in domain:
            if isinstance(token, str) and token in _DOMAIN_BOOL_OPS:
                continue
            if not isinstance(token, (list, tuple)):
                raise ValueError(
                    "Domain leaf must be a tuple, got %s: %r" % (type(token).__name__, token)
                )
            if len(token) != 3:
                raise ValueError(
                    "Domain leaf must have exactly 3 elements (field, operator, value), "
                    "got %d: %r" % (len(token), tuple(token))
                )
            field_name, op, _value = token
            if not isinstance(field_name, str) or not field_name:
                raise ValueError(
                    "Domain leaf field name must be a non-empty string, got: %r" % (field_name,)
                )
            if not isinstance(op, str) or not op:
                raise ValueError(
                    "Domain leaf operator must be a non-empty string, got: %r" % (op,)
                )

    @api.constrains("filter_domain")
    def _check_filter_domain(self):
        for rec in self:
            raw = (rec.filter_domain or "").strip()
            if not raw or raw == "[]":
                continue
            try:
                domain = rec._eval_filter_domain(raw)
                Domain.AND([domain])
                self._validate_domain_leaves(domain)
            except Exception as exc:
                raise ValidationError(
                    _("Custom Domain is not a valid Odoo domain: %s") % exc
                ) from exc

    def _build_filter_domain(self, model_name):
        """Return an ORM domain list for the active filter_preset.

        Always silent: if the required field is absent the filter is skipped
        and an empty domain (no restriction) is returned. This ensures the
        device display path never crashes due to a misconfigured filter.
        """
        if self.filter_preset == "none":
            return []

        existing = set(
            self.env["ir.model.fields"].sudo().search([
                ("model", "=", model_name),
                ("name", "in", _FILTER_DATE_FIELDS + ["user_id"]),
            ]).mapped("name")
        )

        if self.filter_preset == "my_records":
            if "user_id" not in existing:
                return []
            if self.user_ids:
                return [("user_id", "in", self.user_ids.ids)]
            return [("user_id", "=", self.env.uid)]

        date_field = next((f for f in _FILTER_DATE_FIELDS if f in existing), None)
        if not date_field:
            return []

        today = fields.Date.today()

        if self.filter_preset == "today":
            return [(date_field, ">=", today), (date_field, "<", today + timedelta(days=1))]

        if self.filter_preset == "this_week":
            week_start = today - timedelta(days=today.weekday())
            return [(date_field, ">=", week_start), (date_field, "<", week_start + timedelta(days=7))]

        if self.filter_preset == "this_month":
            _, last_day = monthrange(today.year, today.month)
            return [(date_field, ">=", today.replace(day=1)), (date_field, "<=", today.replace(day=last_day))]

        if self.filter_preset == "overdue":
            return [(date_field, "<", today)]

        return []
