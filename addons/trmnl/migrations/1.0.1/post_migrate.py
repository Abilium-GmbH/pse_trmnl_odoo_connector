"""Post-migration script for TRMNL module version 1.0.1.

Runs once when upgrading from any earlier version.  All statements are
idempotent so re-running them on an already-migrated database is safe.
"""


def migrate(cr, version):
    # 1. Convert legacy trmnl_layout='line' profiles to graph/line subtype.
    cr.execute("""
        UPDATE trmnl_profile
           SET trmnl_layout = 'graph', graph_type = 'line'
         WHERE trmnl_layout = 'line'
    """)

    # 2. Backfill graph_type='bar' for graph profiles that pre-date the field.
    cr.execute("""
        UPDATE trmnl_profile
           SET graph_type = 'bar'
         WHERE trmnl_layout = 'graph'
           AND (graph_type IS NULL OR graph_type = '')
    """)

    # 3. Migrate line_title → graph_title for profiles that had a custom title
    #    set via the old line-chart form before graph_title was introduced.
    cr.execute("""
        UPDATE trmnl_profile
           SET graph_title = line_title
         WHERE line_title IS NOT NULL
           AND line_title != ''
           AND (graph_title IS NULL OR graph_title = '')
    """)
