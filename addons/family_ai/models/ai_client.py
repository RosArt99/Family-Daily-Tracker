import logging
import os

from odoo import api, models

_logger = logging.getLogger(__name__)

# Cheapest current model; plenty for short Russian texts built from numbers we computed ourselves.
MODEL = 'claude-haiku-5-5'

BASE_SYSTEM = (
    "You are the assistant inside a private family app (groceries, meals and calories, gym, "
    "finances) used by two people on their iPhones. Always write in Russian, informal "
    "('ты'), warm and to the point. Every number you mention must come from the facts you "
    "are given: never compute new totals or invent data. No markdown, no emojis unless asked."
)


class FamilyAi(models.AbstractModel):
    """One place that talks to the Claude API, so every feature shares the key, the model and
    the error handling. Features compute their facts in Python and only ask Claude for words."""
    _name = 'family.ai'
    _description = 'Claude API client'

    @api.model
    def _is_configured(self):
        return bool(os.environ.get('ANTHROPIC_API_KEY'))

    @api.model
    def _ask(self, prompt, system=None, max_tokens=1500, effort='low'):
        """Send one prompt and return Claude's text, or None when it could not answer (no key,
        network error, refusal...). Callers decide what to do without a text, so a cron never
        crashes because the API had a bad minute."""
        if not self._is_configured():
            _logger.warning('family_ai: ANTHROPIC_API_KEY is not set, skipping the Claude call.')
            return None
        import anthropic  # lazy: keeps Odoo bootable even if the package is missing

        client = anthropic.Anthropic(timeout=60.0, max_retries=2)
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=BASE_SYSTEM + ('\n\n' + system if system else ''),
                output_config={'effort': effort},
                messages=[{'role': 'user', 'content': prompt}],
            )
        except anthropic.AuthenticationError as e:
            _logger.error('family_ai: the API key was rejected: %s', e)
            return None
        except anthropic.RateLimitError as e:
            _logger.warning('family_ai: rate limited: %s', e)
            return None
        except anthropic.APIStatusError as e:
            # 402 billing_error = the prepaid credit has run out.
            _logger.error('family_ai: API error %s (%s): %s', e.status_code, getattr(e, 'type', ''), e)
            return None
        except anthropic.APIConnectionError as e:
            _logger.warning('family_ai: could not reach the API: %s', e)
            return None

        if response.stop_reason == 'refusal':
            _logger.warning('family_ai: Claude declined: %s', response.stop_details)
            return None
        usage = response.usage
        _logger.info('family_ai: %s in / %s out tokens', usage.input_tokens, usage.output_tokens)
        text = ''.join(block.text for block in response.content if block.type == 'text').strip()
        return text or None
