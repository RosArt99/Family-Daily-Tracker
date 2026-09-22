import re

from odoo import SUPERUSER_ID, api

# "70*15", "100 x 12", "120×8" (Latin x, multiplication sign or Cyrillic "х"): weight x reps.
PAIR = re.compile(r'(\d+(?:[.,]\d+)?)\s*[*xX×хХ]\s*(\d+)')
COUNT_WORDS = re.compile(r'\d+\s*(?:series|sets?|подход\w*)\s*:?', re.I)


def migrate(cr, version):
    """Turn the old one-set-per-row entries into sessions (one per person/day/exercise) whose
    sets are the rows themselves, or the "70*15, 100*12" lists that were typed into the notes
    while there was no way to log several sets."""
    cr.execute("SELECT to_regclass('gym_strength_log_legacy')")
    if not cr.fetchone()[0]:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT id, user_id, date, workout_id, exercise_id, weight, reps, notes
        FROM gym_strength_log_legacy ORDER BY id
    """)
    groups = {}
    for row in cr.dictfetchall():
        key = (row['user_id'], row['date'], row['workout_id'], row['exercise_id'])
        groups.setdefault(key, []).append(row)

    Log = env['gym.strength_log']
    for rows in groups.values():
        sets, notes = [], []
        for row in rows:
            text = row['notes'] or ''
            pairs = PAIR.findall(text)
            if pairs:
                sets += [(float(weight.replace(',', '.')), int(reps)) for weight, reps in pairs]
                # Keep the note only if it says more than the sets it just became.
                leftover = COUNT_WORDS.sub('', PAIR.sub('', text))
                if re.sub(r'[\s,;:+\-]+', '', leftover):
                    notes.append(text)
                continue
            if row['weight'] or row['reps']:
                sets.append((row['weight'] or 0.0, row['reps'] or 0))
            if text:
                notes.append(text)
        log = Log.browse(rows[0]['id'])
        env['gym.strength_set'].create([
            {'log_id': log.id, 'sequence': 10 * (index + 1), 'weight': weight, 'reps': reps}
            for index, (weight, reps) in enumerate(sets)
        ])
        log.write({'notes': ' | '.join(dict.fromkeys(notes)) or False})
        Log.browse([row['id'] for row in rows[1:]]).unlink()

    cr.execute("DROP TABLE gym_strength_log_legacy")
