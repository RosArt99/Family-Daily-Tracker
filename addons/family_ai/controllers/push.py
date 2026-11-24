import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FamilyPushController(http.Controller):
    """Phone <-> server plumbing for push notifications, on top of what Odoo's mail module already
    has (mail.partner.device stores each phone's subscription, VAPID keys live in system
    parameters). mail only lets admins touch those models, hence these small user routes."""

    @http.route('/family/push/vapid_key', type='json', auth='user')
    def vapid_key(self):
        # Generated on first use and then kept: changing it would log every phone out of push.
        return request.env['mail.partner.device'].sudo().get_web_push_vapid_public_key()

    @http.route('/family/push/subscribe', type='json', auth='user')
    def subscribe(self, subscription, previous_endpoint=None):
        """`subscription` is the browser's PushSubscription.toJSON(): endpoint + keys."""
        Device = request.env['mail.partner.device'].sudo()
        kwargs = dict(subscription or {}, vapid_public_key=Device.get_web_push_vapid_public_key())
        if previous_endpoint:
            kwargs['previousEndpoint'] = previous_endpoint
        # sudo() keeps the current user, so the device is filed under their own partner.
        Device.register_devices(**kwargs)
        return {'ok': True, 'devices': self._device_count()}

    @http.route('/family/push/unsubscribe', type='json', auth='user')
    def unsubscribe(self, endpoint):
        request.env['mail.partner.device'].sudo().unregister_devices(endpoint=endpoint)
        return {'ok': True, 'devices': self._device_count()}

    @http.route('/family/push/status', type='json', auth='user')
    def status(self, endpoint=None):
        Device = request.env['mail.partner.device'].sudo()
        partner = request.env.user.partner_id
        this_device = bool(endpoint) and bool(
            Device.search_count([('endpoint', '=', endpoint), ('partner_id', '=', partner.id)]))
        return {
            'devices': self._device_count(),
            'this_device': this_device,
            'ai_configured': request.env['family.ai']._is_configured(),
        }

    @http.route('/family/push/test', type='json', auth='user')
    def test(self):
        """Ask Claude for a short hello and push it: proves the key, the model and the push path
        in one tap. Without an answer from Claude the push still goes out, saying why."""
        user = request.env.user
        name = (user.name or '').split(' ')[0]
        text = request.env['family.ai']._ask(
            'Напиши одно короткое (до 20 слов) дружелюбное приветствие для %s: уведомления '
            'от семейного помощника теперь работают на этом телефоне.' % name,
            max_tokens=500,
        )
        if not text:
            text = ('Push работает, но помощник не ответил: проверь ключ ANTHROPIC_API_KEY '
                    'и лог Odoo (family_ai).')
        message = request.env['family.ai.message']._post(user, 'test', 'Проверка уведомлений', text)
        return {'ok': True, 'message_id': message.id, 'pushed': message.pushed, 'text': text}

    def _device_count(self):
        return request.env['mail.partner.device'].sudo().search_count(
            [('partner_id', '=', request.env.user.partner_id.id)])
