from . import models


def post_init_hook(env):
    """First install only: the household's books are in zlotys (it spends in PLN), and the
    currencies it earns/saves in must be switchable. Later changes to the company currency are
    left alone."""
    for name in ('PLN', 'UAH', 'USD'):
        env['res.currency'].with_context(active_test=False).search([('name', '=', name)]).active = True
    company = env.ref('base.main_company')
    pln = env['res.currency'].search([('name', '=', 'PLN')], limit=1)
    if pln and company.currency_id != pln:
        company.currency_id = pln
