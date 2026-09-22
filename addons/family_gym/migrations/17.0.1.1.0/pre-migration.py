def migrate(cr, version):
    """Exercises became sessions with several sets: keep the old one-set-per-row data aside.

    Odoo drops the columns of fields that no longer exist at the end of the upgrade, so the old
    weight/reps are copied to a plain table here and turned into sets in post-migration.py.
    """
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'gym_strength_log' AND column_name = 'weight'
    """)
    if cr.fetchone():
        cr.execute("""
            CREATE TABLE gym_strength_log_legacy AS
            SELECT id, user_id, date, workout_id, exercise_id, weight, reps, notes
            FROM gym_strength_log
        """)
