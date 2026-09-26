import json

from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.webmanifest import WebManifest

HOME_COLOR = '#3B4A54'
SPLASH_COLOR = '#FFF6E8'  # the logo's own background
ICON_DIR = '/family_tracker/static/src/img/pwa'
# Bump when the icon files change: iOS and Safari cache home-screen icons by URL.
ICON_VERSION = 4


class GroceriesWebManifest(WebManifest):

    # Same route as the parent, so this replaces its handler; we only rewrite the payload.
    @http.route('/web/manifest.webmanifest', type='http', auth='public', methods=['GET'])
    def webmanifest(self):
        response = super().webmanifest()
        manifest = json.loads(response.get_data(as_text=True))

        menu_id = request.env['ir.model.data'].sudo()._xmlid_to_res_id(
            'family_tracker.menu_home_root', raise_if_not_found=False)
        manifest.update({
            'name': 'Family',
            'short_name': 'Family',
            # Opens the Home page (tiles for every family app).
            'start_url': '/web#menu_id=%s' % menu_id if menu_id else '/web',
            'background_color': SPLASH_COLOR,
            'theme_color': HOME_COLOR,
            'orientation': 'portrait',
            'icons': [
                {'src': '%s/icon-192.png?v=%s' % (ICON_DIR, ICON_VERSION), 'sizes': '192x192', 'type': 'image/png'},
                {'src': '%s/icon-512.png?v=%s' % (ICON_DIR, ICON_VERSION), 'sizes': '512x512', 'type': 'image/png',
                 'purpose': 'any'},
                {'src': '%s/icon-512-maskable.png?v=%s' % (ICON_DIR, ICON_VERSION), 'sizes': '512x512',
                 'type': 'image/png', 'purpose': 'maskable'},
            ],
            'shortcuts': [],
        })
        response.set_data(json.dumps(manifest))
        return response
