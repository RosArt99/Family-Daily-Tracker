import json

from odoo import api, fields, models

PUSH_ICON = '/family_tracker/static/src/img/pwa/icon-192.png'
PUSH_BODY_MAX = 600


class FamilyAiMessage(models.Model):
    """A message from the assistant to one person (a protein tip, a month report...). It is kept
    here so the push notification can open it in full, and as a feed to scroll back through."""
    _name = 'family.ai.message'
    _description = 'Assistant message'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one('res.users', string='For', required=True, index=True, ondelete='cascade')
    kind = fields.Selection([
        ('test', 'Test'),
        ('protein', 'Protein'),
        ('finance_forecast', 'Finance forecast'),
        ('finance_month', 'Month report'),
        ('other', 'Other'),
    ], required=True, default='other', index=True)
    title = fields.Char(required=True)
    body = fields.Text(required=True)
    is_read = fields.Boolean(default=False)
    pushed = fields.Boolean(string='Push sent', readonly=True)
    # What the message is about, e.g. "protein:2026-11-24" or "finance_month:2026-10": the hourly
    # cron checks it so nobody gets the same message twice.
    period_key = fields.Char(index=True, readonly=True)

    @api.model
    def _already_sent(self, user, period_key):
        return bool(self.sudo().search_count([('user_id', '=', user.id), ('period_key', '=', period_key)]))

    @api.model
    def _post(self, user, kind, title, body, push=True, period_key=False):
        """Store a message for `user` and (by default) send it to every phone they enabled
        notifications on. Runs as superuser: crons and other people's actions create these."""
        message = self.sudo().create({
            'user_id': user.id, 'kind': kind, 'title': title, 'body': body, 'period_key': period_key,
        })
        if push:
            message._push()
        return message

    def _push(self):
        WebPush = self.env['mail.notification.web.push'].sudo()
        Device = self.env['mail.partner.device'].sudo()
        queued = False
        for message in self.sudo():
            devices = Device.search([('partner_id', '=', message.user_id.partner_id.id)])
            if not devices:
                continue
            payload = json.dumps({
                'title': message.title,
                'options': {
                    # Push payloads are capped at ~4 KB; tapping opens the full text anyway.
                    'body': message.body if len(message.body) <= PUSH_BODY_MAX
                    else message.body[:PUSH_BODY_MAX - 1].rstrip() + '…',
                    'icon': PUSH_ICON,
                    'tag': 'family_ai_%s' % message.id,
                    # mail's service worker opens /web#model=...&id=... on tap.
                    'data': {'model': self._name, 'res_id': message.id},
                },
            })
            WebPush.create([{'user_device': device.id, 'payload': payload} for device in devices])
            message.pushed = True
            queued = True
        if queued:
            # mail's own cron does the encrypted sending; run it now instead of on its schedule.
            self.env.ref('mail.ir_cron_web_push_notification').sudo()._trigger()

    def action_mark_read(self):
        self.write({'is_read': True})
