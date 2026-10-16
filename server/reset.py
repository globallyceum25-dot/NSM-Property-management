"""Maintenance helper.

    python3 -m server.reset --wipe     delete every property, document and property type
                                       (including the sample seed data) and the
                                       uploaded files, then recreate an empty
                                       schema.
    python3 -m server.reset --sample   drop everything and reload the sample
                                       data instead.
"""

import argparse

from . import db, storage


def wipe(reload_sample=False):
    conn = db.get_conn()
    if db.IS_POSTGRES:
        conn.executescript("TRUNCATE %s RESTART IDENTITY;" % ", ".join(db.TABLES))
    else:
        conn.executescript("""
            DELETE FROM document;
            DELETE FROM property;
            DELETE FROM location_code;
            DELETE FROM location;
            DELETE FROM sbu;
            DELETE FROM legal_entity;
            DELETE FROM sqlite_sequence
             WHERE name IN ('document','property','sbu','legal_entity',
                            'location','location_code');
        """)
    conn.commit()
    storage.clear()
    if reload_sample:
        db.seed(conn)
        print("Database cleared and sample data reloaded.")
    else:
        print("Database cleared. Add your SBUs from the Business units tab.")


def main():
    parser = argparse.ArgumentParser(description="Reset the property register")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--wipe", action="store_true", help="empty the register")
    group.add_argument("--sample", action="store_true", help="reload sample data")
    args = parser.parse_args()

    db.init_db()
    target = "sample data" if args.sample else "an empty register"
    answer = input("This deletes all properties, documents and uploads in %s,\n"
                   "leaving %s.\nType DELETE to continue: " % (db.describe(), target))
    if answer.strip() != "DELETE":
        print("Cancelled.")
        return
    wipe(reload_sample=args.sample)


if __name__ == "__main__":
    main()
