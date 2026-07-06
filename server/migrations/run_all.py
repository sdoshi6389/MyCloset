"""Run all migrations in order. Safe to re-run (idempotent SQL)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrations import migration_001, migration_002, migration_003, migration_004

migration_001.run()
migration_002.run()
migration_003.run()
migration_004.run()
print("✅ All migrations complete.")
