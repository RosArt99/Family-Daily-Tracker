from odoo import fields, models

MUSCLE_GROUPS = [
    ('chest', 'Chest'),
    ('back', 'Back'),
    ('legs', 'Legs'),
    ('shoulders', 'Shoulders'),
    ('arms', 'Arms'),
    ('core', 'Core'),
    ('cardio', 'Cardio'),
    ('other', 'Other'),
]


class GymExercise(models.Model):
    _name = 'gym.exercise'
    _description = 'Gym Exercise'
    _order = 'name'

    name = fields.Char(required=True)
    # Stable key so default filters/graphs can reference an exercise without depending on its id.
    code = fields.Char(copy=False)
    muscle_group = fields.Selection(MUSCLE_GROUPS, string='Muscle Group', default='other')
    metric = fields.Selection([
        ('strength', 'Weight x reps'),
        ('reps', 'Reps (bodyweight)'),
    ], string='Progress Metric', default='strength', required=True,
        help='What the progress graph tracks: the heaviest weight for weighted lifts, '
             'or the most reps for bodyweight exercises such as pull-ups.')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'An exercise with this name already exists.'),
        ('code_uniq', 'unique(code)', 'This exercise code is already used.'),
    ]
