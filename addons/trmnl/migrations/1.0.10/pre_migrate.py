"""Pre-migration script for TRMNL module version 1.0.10.

Converts trmnl.profile's user_id (Many2one → res.users) to user_ids
(Many2many).  Runs before the ORM upgrade so the old column is still
present and can be read.
"""


def migrate(cr, version):
    # Check that the old Many2one column still exists — skip if already migrated.
    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'trmnl_profile' AND column_name = 'user_id'
    """)
    if not cr.fetchone():
        return

    # Pre-create the Many2many relation table so existing user_id values
    # are preserved.  Odoo's ORM uses CREATE TABLE IF NOT EXISTS on upgrade,
    # so creating it here is safe and idempotent.
    cr.execute("""
        CREATE TABLE IF NOT EXISTS trmnl_profile_res_users_rel (
            profile_id INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            PRIMARY KEY (profile_id, user_id)
        )
    """)
    cr.execute("""
        INSERT INTO trmnl_profile_res_users_rel (profile_id, user_id)
        SELECT id, user_id
          FROM trmnl_profile
         WHERE user_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
