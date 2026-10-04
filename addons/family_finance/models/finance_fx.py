import logging
from datetime import timedelta

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# National Bank of Ukraine's official rates: hryvnias for ONE unit of the currency, per day.
# Everything else is derived from those (PLN per USD = UAH-per-USD / UAH-per-PLN).
NBU_URL = 'https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange'


class FinanceFxRate(models.Model):
    _name = 'finance.fx.rate'
    _description = 'NBU exchange rate (cache)'
    _order = 'date desc'

    currency_id = fields.Many2one('res.currency', required=True, ondelete='cascade', index=True)
    date = fields.Date(required=True, index=True)
    uah_rate = fields.Float(string='UAH per 1 unit', digits=(16, 6), required=True)

    _sql_constraints = [
        ('currency_date_uniq', 'unique(currency_id, date)', 'One rate per currency and day.'),
    ]

    @api.model
    def _fetch_nbu(self, code, day):
        try:
            response = requests.get(
                NBU_URL, params={'valcode': code, 'date': day.strftime('%Y%m%d'), 'json': ''},
                timeout=10)
            response.raise_for_status()
            rows = response.json()
        except (requests.RequestException, ValueError):
            _logger.warning('NBU rate for %s on %s could not be fetched', code, day)
            return None
        return float(rows[0]['rate']) if rows else None

    @api.model
    def _uah_per_unit(self, currency, day):
        """UAH for one unit of `currency` on `day`: cached, else fetched from the NBU, else the
        latest cached rate before that day (offline / holiday). None if nothing is known."""
        if currency.name == 'UAH':
            return 1.0
        cached = self.sudo().search([('currency_id', '=', currency.id), ('date', '=', day)], limit=1)
        if cached:
            return cached.uah_rate
        rate = self._fetch_nbu(currency.name, day)
        if rate:
            self.sudo().create({'currency_id': currency.id, 'date': day, 'uah_rate': rate})
            return rate
        earlier = self.sudo().search(
            [('currency_id', '=', currency.id), ('date', '<=', day)], limit=1)
        return earlier.uah_rate if earlier else None

    @api.model
    def get_rate(self, currency_id, date=None):
        """How many units of the company currency one unit of `currency_id` is worth on `date`.
        Returns {'rate': float|False, 'date': 'YYYY-MM-DD'}; rate is False when unknown."""
        today = fields.Date.context_today(self)
        day = min(fields.Date.to_date(date) if date else today, today + timedelta(days=1))
        base = self.env.company.currency_id
        currency = self.env['res.currency'].browse(currency_id)
        if not currency or currency == base:
            return {'rate': 1.0, 'date': fields.Date.to_string(day)}
        foreign = self._uah_per_unit(currency, day)
        base_uah = self._uah_per_unit(base, day)
        if not foreign or not base_uah:
            return {'rate': False, 'date': fields.Date.to_string(day)}
        return {'rate': round(foreign / base_uah, 6), 'date': fields.Date.to_string(day)}

    @api.model
    def _ensure_rate(self, vals, model):
        """Fill vals['rate'] when the record is in a foreign currency and none was given."""
        base = self.env.company.currency_id
        currency_id = vals.get('currency_id') or base.id
        if currency_id == base.id:
            vals['rate'] = 1.0
        elif not vals.get('rate') or vals['rate'] <= 0:
            result = self.get_rate(currency_id, vals.get('date'))
            if not result['rate']:
                from odoo.exceptions import UserError
                raise UserError('No exchange rate is available for that day - please enter it by hand.')
            vals['rate'] = result['rate']
