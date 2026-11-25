import logging
from datetime import date, datetime, timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Binance public market data: no key needed. Prices are in USDT, which tracks the US dollar.
BINANCE_API = 'https://api.binance.com/api/v3'
PRICE_MAX_AGE = timedelta(minutes=5)   # opening the screen refreshes prices older than this
HTTP_TIMEOUT = 10


class FinanceCryptoAsset(models.Model):
    """A coin you hold (BTC, ETH, XRP), with its latest price in US dollars."""
    _name = 'finance.crypto.asset'
    _description = 'Crypto asset'
    _order = 'sequence, id'

    name = fields.Char(required=True)                 # Bitcoin
    symbol = fields.Char(required=True)               # BTC
    market = fields.Char(required=True, help='Binance pair used for the price, e.g. BTCUSDT.')
    color = fields.Char(default='#999999', help='Line colour on the chart.')
    sequence = fields.Integer(default=10)
    price_usd = fields.Float(string='Price (USD)', digits=(16, 6), readonly=True)
    price_at = fields.Datetime(string='Price checked', readonly=True)
    lot_ids = fields.One2many('finance.crypto.lot', 'asset_id', string='Purchases')

    _sql_constraints = [('symbol_uniq', 'unique(symbol)', 'This coin is already in the list.')]

    # ------------------------------------------------------------------ prices

    @api.model
    def _refresh_prices(self, force=False):
        """Latest price of every coin, one call for all of them."""
        assets = self.sudo().search([])
        stale = assets if force else assets.filtered(
            lambda a: not a.price_at or fields.Datetime.now() - a.price_at > PRICE_MAX_AGE)
        if not stale:
            return
        try:
            response = requests.get('%s/ticker/price' % BINANCE_API, timeout=HTTP_TIMEOUT, params={
                'symbols': '[%s]' % ','.join('"%s"' % a.market for a in stale)})
            response.raise_for_status()
            prices = {row['symbol']: float(row['price']) for row in response.json()}
        except (requests.RequestException, ValueError, KeyError) as error:
            _logger.warning('Crypto: could not get prices from Binance: %s', error)
            return
        now = fields.Datetime.now()
        for asset in stale:
            if asset.market in prices:
                asset.write({'price_usd': prices[asset.market], 'price_at': now})

    def _refresh_history(self):
        """Daily closing prices from the first purchase to today (only the missing days)."""
        Price = self.env['finance.crypto.price'].sudo()
        today = fields.Date.context_today(self)
        for asset in self.sudo():
            first = min(asset.lot_ids.mapped('date') or [False]) if asset.lot_ids else False
            if not first:
                continue
            start = first.date() - timedelta(days=1)
            last = Price.search([('asset_id', '=', asset.id)], order='day desc', limit=1)
            if last and last.day >= today - timedelta(days=1):
                start = None
            elif last:
                start = max(start, last.day + timedelta(days=1))
            if start is None:
                continue
            try:
                response = requests.get('%s/klines' % BINANCE_API, timeout=HTTP_TIMEOUT, params={
                    'symbol': asset.market, 'interval': '1d', 'limit': 1000,
                    'startTime': int(datetime.combine(start, datetime.min.time()).timestamp() * 1000)})
                response.raise_for_status()
                rows = response.json()
            except (requests.RequestException, ValueError) as error:
                _logger.warning('Crypto: could not get %s history from Binance: %s', asset.symbol, error)
                continue
            known = set(Price.search([('asset_id', '=', asset.id), ('day', '>=', start)]).mapped('day'))
            values = []
            for row in rows:
                day = datetime.utcfromtimestamp(row[0] / 1000).date()
                if day < today and day not in known:     # today's candle is not closed yet
                    values.append({'asset_id': asset.id, 'day': day, 'close': float(row[4])})
            if values:
                Price.create(values)

    @api.model
    def _cron_refresh(self):
        self._refresh_prices(force=True)
        self.search([])._refresh_history()


class FinanceCryptoPrice(models.Model):
    """Closing price of a coin on one day (UTC), for the chart."""
    _name = 'finance.crypto.price'
    _description = 'Crypto daily price'
    _order = 'day'

    asset_id = fields.Many2one('finance.crypto.asset', required=True, ondelete='cascade', index=True)
    day = fields.Date(required=True, index=True)
    close = fields.Float(digits=(16, 6), required=True)

    _sql_constraints = [('asset_day_uniq', 'unique(asset_id, day)', 'One price per coin and day.')]


class FinanceCryptoLot(models.Model):
    """One purchase ("lot"): how much of a coin, at what price, what it cost. Each lot keeps its
    own profit or loss, so a buy at 77 000 and another at 55 000 show separately."""
    _name = 'finance.crypto.lot'
    _description = 'Crypto purchase'
    _order = 'date desc, id desc'

    asset_id = fields.Many2one('finance.crypto.asset', string='Coin', required=True, ondelete='restrict', index=True)
    date = fields.Datetime(string='Bought on', required=True, default=fields.Datetime.now)
    quantity = fields.Float(string='Amount bought', digits=(16, 8), required=True)
    price_usd = fields.Float(string='Price (USD)', digits=(16, 6), required=True)
    fee = fields.Float(string='Fee', digits=(16, 8))
    fee_in = fields.Selection([('coin', 'In the coin'), ('usd', 'In USD')], default='coin', required=True,
                              help='Binance usually takes the fee from the coin you receive.')
    total_usd = fields.Float(string='Total paid (USD)', digits=(16, 6),
                             help='What the order cost (USDT/USDC). Empty: amount x price (+ a USD fee).')
    quote = fields.Selection([('USDT', 'USDT'), ('USDC', 'USDC'), ('USD', 'USD')], default='USDT', required=True)
    order_type = fields.Selection([('market', 'Market'), ('limit', 'Limit')], default='market')
    order_no = fields.Char(string='Order No.')
    exchange = fields.Char(default='Binance')
    notes = fields.Char()
    user_id = fields.Many2one('res.users', string='Bought by', default=lambda self: self.env.user)

    net_quantity = fields.Float(string='Amount held', digits=(16, 8), compute='_compute_amounts', store=True)
    cost_usd = fields.Float(string='Cost (USD)', digits=(16, 6), compute='_compute_amounts', store=True)

    _sql_constraints = [
        ('quantity_positive', 'check(quantity > 0)', 'The amount must be above zero.'),
        ('price_positive', 'check(price_usd > 0)', 'The price must be above zero.'),
    ]

    @api.depends('quantity', 'price_usd', 'fee', 'fee_in', 'total_usd')
    def _compute_amounts(self):
        for lot in self:
            fee_coin = lot.fee if lot.fee_in == 'coin' else 0.0
            fee_usd = lot.fee if lot.fee_in == 'usd' else 0.0
            lot.net_quantity = lot.quantity - fee_coin
            lot.cost_usd = lot.total_usd or (lot.quantity * lot.price_usd + fee_usd)

    # ------------------------------------------------------------------ the Crypto screen

    @api.model
    def _lot_row(self, lot, price):
        value = lot.net_quantity * price
        pnl = value - lot.cost_usd
        return {
            'id': lot.id,
            'date': fields.Datetime.to_string(lot.date),
            'quantity': lot.quantity,
            'net_quantity': lot.net_quantity,
            'price': lot.price_usd,
            'fee': lot.fee,
            'fee_in': lot.fee_in,
            'total': lot.total_usd,
            'cost': lot.cost_usd,
            'quote': lot.quote,
            'order_type': lot.order_type,
            'order_no': lot.order_no or '',
            'notes': lot.notes or '',
            'value': value,
            'pnl': pnl,
            'pnl_pct': (pnl / lot.cost_usd * 100.0) if lot.cost_usd else 0.0,
        }

    @api.model
    def get_portfolio(self):
        """Everything the Crypto screen shows: totals, per coin (with every lot), chart series."""
        Asset = self.env['finance.crypto.asset']
        Asset._refresh_prices()
        assets = Asset.search([])
        assets.filtered('lot_ids')._refresh_history()
        coins = []
        total_value = total_cost = 0.0
        for asset in assets:
            lots = asset.lot_ids.sorted(lambda l: (l.date, l.id))
            rows = [self._lot_row(lot, asset.price_usd) for lot in lots]
            held = sum(lots.mapped('net_quantity'))
            cost = sum(lots.mapped('cost_usd'))
            value = held * asset.price_usd
            total_value += value
            total_cost += cost
            coins.append({
                'id': asset.id, 'symbol': asset.symbol, 'name': asset.name, 'color': asset.color,
                'price': asset.price_usd,
                'price_at': fields.Datetime.to_string(asset.price_at) if asset.price_at else False,
                'held': held, 'cost': cost, 'value': value, 'pnl': value - cost,
                'pnl_pct': ((value - cost) / cost * 100.0) if cost else 0.0,
                'avg_price': (cost / held) if held else 0.0,
                'lots': list(reversed(rows)),   # newest first
            })
        return {
            'can_edit': self.check_access_rights('create', raise_exception=False),
            'value': total_value,
            'cost': total_cost,
            'pnl': total_value - total_cost,
            'pnl_pct': ((total_value - total_cost) / total_cost * 100.0) if total_cost else 0.0,
            'coins': coins,
            'chart': self._chart(assets),
        }

    @api.model
    def _chart(self, assets):
        """Value of what you held of each coin, day by day, since the first purchase:
        {days: [...], series: [{symbol, color, values: [...]}]}. Today uses the live price."""
        lots = self.search([], order='date')
        if not lots:
            return {'days': [], 'series': []}
        today = fields.Date.context_today(self)
        first = min(lots.mapped('date')).date()
        days = [first + timedelta(days=n) for n in range((today - first).days + 1)]
        series = []
        for asset in assets:
            asset_lots = lots.filtered(lambda l: l.asset_id == asset)
            if not asset_lots:
                continue
            closes = {p.day: p.close for p in self.env['finance.crypto.price'].sudo().search([('asset_id', '=', asset.id)])}
            values, last_close = [], 0.0
            for day in days:
                close = asset.price_usd if day == today else closes.get(day, last_close)
                last_close = close or last_close
                held = sum(l.net_quantity for l in asset_lots if l.date.date() <= day)
                values.append(round(held * last_close, 2))
            series.append({'symbol': asset.symbol, 'color': asset.color, 'values': values})
        return {'days': [d.isoformat() for d in days], 'series': series}

    @api.model
    def save_lot(self, values):
        """Create or update a purchase from the screen's form."""
        vals = {
            'asset_id': values['asset_id'],
            'date': values.get('date') or fields.Datetime.now(),
            'quantity': float(values.get('quantity') or 0),
            'price_usd': float(values.get('price') or 0),
            'fee': float(values.get('fee') or 0),
            'fee_in': values.get('fee_in') or 'coin',
            'total_usd': float(values.get('total') or 0),
            'quote': values.get('quote') or 'USDT',
            'order_type': values.get('order_type') or 'market',
            'order_no': values.get('order_no') or False,
            'notes': values.get('notes') or False,
        }
        if vals['quantity'] <= 0 or vals['price_usd'] <= 0:
            raise UserError(_('Fill in the amount and the price.'))
        if values.get('id'):
            self.browse(values['id']).write(vals)
        else:
            self.create(vals)
        return self.get_portfolio()

    @api.model
    def delete_lot(self, lot_id):
        self.browse(lot_id).unlink()
        return self.get_portfolio()

    @api.model
    def get_summary(self):
        """Small card for the Finance Overview (no API calls: last known prices)."""
        lots = self.sudo().search([])
        value = sum(lot.net_quantity * lot.asset_id.price_usd for lot in lots)
        cost = sum(lots.mapped('cost_usd'))
        return {'has_lots': bool(lots), 'value': value, 'cost': cost, 'pnl': value - cost,
                'pnl_pct': ((value - cost) / cost * 100.0) if cost else 0.0}
