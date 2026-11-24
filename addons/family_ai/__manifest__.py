{
    'name': 'Family Assistant',
    'version': '17.0.1.3.0',
    'category': 'Productivity',
    'summary': 'Claude-written tips and reports for the family, delivered as iPhone push notifications',
    'author': 'Ros',
    'license': 'LGPL-3',
    'depends': ['mail', 'family_tracker', 'family_gym', 'family_finance'],
    'external_dependencies': {'python': ['anthropic']},
    'data': [
        'security/ir.model.access.csv',
        'security/ai_security.xml',
        'data/ir_cron_data.xml',
        'views/ai_message_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'family_ai/static/src/js/push_card.js',
            'family_ai/static/src/js/chat.js',
            'family_ai/static/src/xml/push_card.xml',
            'family_ai/static/src/xml/chat.xml',
            'family_ai/static/src/scss/family_ai.scss',
        ],
    },
    'installable': True,
    'application': False,
}
