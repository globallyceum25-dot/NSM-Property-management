"""Maintenance helper.

    python3 -m server.reset --wipe     delete every property, document and property type
                                       (including the sample seed data) and the
                                       uploaded files, then recreate an empty
                                       schema.
    python3 -m server.reset --sample   drop everything and reload the sample
                                       data instead.
"""

import argparse
import os
import shutil

from . import db


def wipe(reload_sample=False):
    conn = db.get_conn()
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
    if os.path.isdir(db.UPLOAD_DIR):
        shutil.rmtree(db.UPLOAD_DIR)
    os.makedirs(db.UPLOAD_DIR, exist_ok=True)
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
    answer = input("This deletes all properties, documents and uploads, leaving %s.\n"
                   "Type DELETE to continue: " % target)
    if answer.strip() != "DELETE":
        print("Cancelled.")
        return
    wipe(reload_sample=args.sample)


if __name__ == "__main__":
    main()
