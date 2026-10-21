import logging
from datetime import timezone

import pytz

from odoo import fields, http
from odoo.http import request

from .weight_sync import parse_aware, user_from_api_key

_logger = logging.getLogger(__name__)


class GymVisitSyncController(http.Controller):
    """Gym visits from the iPhone, driven by the club's Wi-Fi (the gym is inside a mall, so
    a location trigger would fire for the whole mall - the club's network name does not).

    Two Shortcuts automations call this with the same personal API key as the weight sync:
      "When I join <club Wi-Fi>"   ->  POST /gym/visit  {"event": "join"}
      "When I leave <club Wi-Fi>"  ->  POST /gym/visit  {"event": "leave"}
    `at` (ISO 8601) is optional; without it the server's clock is used.
    """

    @http.route('/gym/visit', type='http', auth='public', methods=['POST'], csrf=False,
                save_session=False)
    def sync_visit(self, **_kwargs):
        uid = user_from_api_key()
        if not uid:
            return self._reply({'error': 'Invalid or missing API key.'}, 401)
        request.update_env(user=uid)

        try:
            payload = request.get_json_data()
        except ValueError:
            payload = {}
        event = str((payload or {}).get('event') or '').lower()
        if event not in ('join', 'leave'):
            return self._reply({'error': 'Send JSON like {"event": "join"} or {"event": "leave"}.'}, 400)
        try:
            moment = self._parse_time((payload or {}).get('at'))
        except ValueError as error:
            return self._reply({'error': 'at must be ISO 8601, e.g. 2026-10-21T18:05:00+02:00 (%s).' % error}, 400)

        result = request.env['gym.workout'].wifi_event(event, moment)
        _logger.info('Gym visit event %s for user %s: %s', event, uid, result)
        return self._reply(result)

    @staticmethod
    def _parse_time(value):
        """Naive UTC datetime of the event (now when not given)."""
        if not value:
            return fields.Datetime.now()
        dt = parse_aware(value)
        if dt.tzinfo is None:
            dt = pytz.timezone(request.env.user.tz or 'UTC').localize(dt)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _reply(data, status=200):
        return request.make_json_response(data, status=status)
