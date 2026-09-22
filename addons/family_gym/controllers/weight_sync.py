import logging
from datetime import datetime, timezone

import pytz

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

API_KEY_SCOPE = 'family_scale'
LB_TO_KG = 0.45359237
MIN_KG, MAX_KG = 20.0, 300.0


class GymWeightSyncController(http.Controller):
    """Receives weigh-ins from the iPhone Shortcut (Zepp Life -> Apple Health -> here).

    The Shortcut has no browser session, so instead of a login it sends a personal API key
    (`Authorization: Bearer <key>`). The key belongs to one user, so *who* was weighed is
    decided by the key, not by anything in the payload.
    """

    @http.route('/gym/weight', type='http', auth='public', methods=['POST'], csrf=False,
                save_session=False)
    def sync_weight(self, **_kwargs):
        headers = request.httprequest.headers
        auth = headers.get('Authorization', '')
        key = auth[7:].strip() if auth.lower().startswith('bearer ') else headers.get('X-Api-Key', '').strip()
        uid = key and request.env['res.users.apikeys']._check_credentials(scope=API_KEY_SCOPE, key=key)
        if not uid:
            return self._reply({'error': 'Invalid or missing API key.'}, 401)
        request.update_env(user=uid)  # from here on record rules apply as that user

        try:
            payload = request.get_json_data()
            weight = float(payload['weight'])
        except (ValueError, TypeError, KeyError):
            return self._reply({'error': 'Send JSON like {"weight": 101.8}.'}, 400)

        unit = str(payload.get('unit') or 'kg').lower()
        if unit in ('lb', 'lbs', 'pound', 'pounds'):
            weight *= LB_TO_KG
        elif unit not in ('kg', 'kilogram', 'kilograms'):
            return self._reply({'error': 'Unknown unit: %s (use kg or lb).' % unit}, 400)
        weight = round(weight, 2)
        if not MIN_KG <= weight <= MAX_KG:
            return self._reply({'error': 'Weight %s kg is outside %s-%s.' % (weight, MIN_KG, MAX_KG)}, 400)

        try:
            measured_at, day = self._parse_time(payload.get('measured_at'))
        except ValueError:
            return self._reply(
                {'error': 'measured_at must be ISO 8601, e.g. 2026-09-21T07:30:00+02:00.'}, 400)

        WeightLog = request.env['gym.weight_log']
        domain = [('user_id', '=', uid), ('source', '=', 'scale')]
        # The exact timestamp identifies a weigh-in; without one fall back to date + value.
        domain += [('measured_at', '=', measured_at)] if measured_at else [
            ('date', '=', day), ('weight', '=', weight)]
        existing = WeightLog.search(domain, limit=1)
        if existing:
            return self._reply({'status': 'exists', 'id': existing.id, 'weight': existing.weight})

        record = WeightLog.create({
            'user_id': uid, 'date': day, 'weight': weight,
            'source': 'scale', 'measured_at': measured_at,
        })
        _logger.info('Scale weigh-in: user %s, %s kg on %s', uid, weight, day)
        return self._reply({'status': 'created', 'id': record.id, 'weight': record.weight}, 201)

    @staticmethod
    def _parse_time(value):
        """Return (naive UTC datetime or False, local date). No value -> today, no dedup key."""
        if not value:
            return False, fields.Date.context_today(request.env.user.with_context(tz=request.env.user.tz))
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:  # naive: assume the user's own timezone
            dt = pytz.timezone(request.env.user.tz or 'UTC').localize(dt)
        return dt.astimezone(timezone.utc).replace(tzinfo=None), dt.date()

    @staticmethod
    def _reply(data, status=200):
        return request.make_json_response(data, status=status)
