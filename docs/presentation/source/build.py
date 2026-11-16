"""Build the presentation: one self-contained HTML file.

    python build.py FRAMES_DIR [OUT_HTML]

FRAMES_DIR is what capture.py wrote. The figures and the role matrix are read
from the live register (data/properties.db, read-only) at build time, so a
rebuild brings them up to date. Needs Pillow for the WebP screens.
"""

import base64
import datetime
import io
import json
import os
import sqlite3
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

from server import access, srilanka  # noqa: E402

TENURE_OWNED = {"FREEHOLD"}
UNIT_LABELS = {"PERCH": "perch", "ROOD": "rood", "ACRE": "acre", "HECTARE": "hectare", "SQ_M": "m²"}


def data_uri(raw, mime):
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def webp(path, quality=80):
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "WEBP", quality=quality, method=6)
    return data_uri(buf.getvalue(), "image/webp")


def demos(frames):
    with open(os.path.join(frames, "manifest.json")) as fh:
        manifest = json.load(fh)
    out = {}
    for module in manifest["modules"]:
        out[module["key"]] = {"url": module["url"], "steps": [
            {"src": webp(os.path.join(frames, s["img"])), "hot": s["hot"], "label": s["label"],
             "cur": s["cur"], "click": s["click"], "hold": s["hold"]} for s in module["steps"]]}
    return out


def stats(conn):
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    total = one("SELECT COUNT(*) FROM property")
    owned = one("SELECT COUNT(*) FROM property WHERE ownership_type IN (%s)"
                % ",".join("'%s'" % t for t in TENURE_OWNED))
    by_type = [{"label": r[0], "color": r[1], "n": r[2]} for r in conn.execute(
        """SELECT s.name, s.color, COUNT(p.id) FROM sbu s LEFT JOIN property p ON p.sbu_id = s.id
           GROUP BY s.id ORDER BY COUNT(p.id) DESC, s.name""")]
    owners = [{"label": r[0], "n": r[1]} for r in conn.execute(
        """SELECT e.short_code, COUNT(*) FROM property p JOIN legal_entity e ON e.id = p.legal_entity_id
           GROUP BY e.id ORDER BY COUNT(*) DESC, e.short_code""")]
    none = one("SELECT COUNT(*) FROM property WHERE legal_entity_id IS NULL")
    districts = [{"label": r[0], "n": r[1]} for r in conn.execute(
        "SELECT district, COUNT(*) FROM property WHERE district IS NOT NULL GROUP BY district ORDER BY 2 DESC")]
    return {
        "date": datetime.date.today().strftime("%-d %B %Y"),
        "total": total, "owned": owned, "leased": total - owned,
        "types": len(by_type), "typesUsed": sum(1 for t in by_type if t["n"]),
        "byType": [t for t in by_type if t["n"]],
        "owners": len(owners),
        "byOwner": owners + ([{"label": "No group company", "n": none, "color": "#b3bfbd"}] if none else []),
        "districts": len(districts), "topDistricts": districts[:5],
        "documents": one("SELECT COUNT(*) FROM document"),
        "units": [[UNIT_LABELS[k], "{:,.2f}".format(v).rstrip("0").rstrip(".")]
                  for k, v in srilanka.SQFT_PER_UNIT.items() if k in UNIT_LABELS],
        "docTypes": [label for _, label in srilanka.DOCUMENT_TYPES],
    }


def roles(conn):
    """Each role's reach per module, as the workbook's Role summary puts it."""
    modules = [m for m in access.MODULES]
    out = []
    for code, name in conn.execute("SELECT code, name FROM app_role ORDER BY sort_order, name"):
        if code == access.SUPER_ADMIN:
            levels = {k: "yes" for k in access.ALL_KEYS}
        else:
            levels = {k: "no" for k in access.ALL_KEYS}
            levels.update({p: lv for p, lv in conn.execute(
                "SELECT permission, level FROM app_role_permission WHERE role_code = ?", (code,))})
        cells = []
        for m in modules:
            acts = [a for a in m["actions"] if a["status"] != "coming"]
            allowed = [a for a in acts if levels.get(a["key"], "no") != "no"]
            if not allowed:
                cells.append("No access")
            elif len(allowed) == len(acts) and all(levels[a["key"]] == "yes" for a in allowed):
                cells.append("Full")
            elif len(acts) > 1 and len(allowed) == 1 and allowed[0]["key"].endswith(".view") \
                    and levels[allowed[0]["key"]] == "yes":
                cells.append("View only")
            else:
                cells.append("Partial")      # some actions, or limited to the person's scope
        out.append({"name": name, "cells": cells})
    short = {"Portfolio (properties)": "Portfolio", "User & access management": "Users & access",
             "Alerts & reminders": "Alerts", "System & audit": "Audit"}
    return {"modules": [short.get(m["label"], m["label"]) for m in modules], "roles": out}


def sprite():
    with open(os.path.join(REPO, "web", "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    start = html.index('<svg xmlns="http://www.w3.org/2000/svg" style="display:none">')
    return html[start:html.index("</svg>", start) + len("</svg>")]


def main():
    frames = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "Property_Register_Presentation.html")
    conn = sqlite3.connect("file:%s?mode=ro" % os.path.join(REPO, "data", "properties.db"), uri=True)
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as fh:
        html = fh.read()
    with open(os.path.join(REPO, "web", "img", "serengeti-logo.png"), "rb") as fh:
        logo = data_uri(fh.read(), "image/png")
    for key, value in (("__SPRITE__", sprite()), ("__LOGO__", logo),
                       ("__MONTH__", datetime.date.today().strftime("%B %Y")),
                       ("__STATS__", json.dumps(stats(conn))), ("__ROLES__", json.dumps(roles(conn))),
                       ("__DEMOS__", json.dumps(demos(frames)))):
        html = html.replace(key, value)
    conn.close()
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("Wrote %s (%.1f MB)" % (os.path.abspath(out), os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
