"""Who may do what: modules and actions, roles, each person's data scope, and
the check every API request passes before its handler runs.

The catalog and the starting roles come from the approved workbook
docs/access/Property Register - Roles and Access.xlsx. Each role gives every
action one of three levels:

    yes      allowed for everything in the role's reach
    limited  allowed with the restriction the action's `limited` note explains:
             usually only the person's assigned property types and owning
             companies, or only what they uploaded themselves
    no       not allowed; the screen does not offer it

Nothing here trusts the browser: the screens hide what a person cannot use, but
every request is checked again on the server, and a route with no permission
entry is refused.
"""

import datetime
import re
from typing import Dict, List

from .errors import ApiError

LEVELS = ("no", "limited", "yes")
SUPER_ADMIN = "SUPER_ADMIN"

SCOPE_NOTE = "Only properties of the person's assigned property types and owning companies."


def _action(key, label, description, limited=None, status="available"):
    return {"key": key, "label": label, "description": description,
            "limited": limited, "status": status}


# The modules of the register and the actions each one offers (workbook: Modules
# and Permissions). `limited` says what "Limited" means for that action; an
# action without it is simply allowed or not.
MODULES = [
    {"key": "properties", "label": "Portfolio (properties)",
     "description": "Property cards, map and table; property details; New property; CSV export.",
     "actions": [
         _action("properties.view", "View", "See the property cards, map and table, and open a property's details.",
                 SCOPE_NOTE),
         _action("properties.create", "Create", "Add a property with New property.",
                 "Only for their assigned property types and owning companies."),
         _action("properties.edit", "Edit", "Change a property's details, map pin, areas and values.", SCOPE_NOTE),
         _action("properties.delete", "Delete", "Delete a property, together with its documents."),
         _action("properties.export", "Export", "Download the register as a CSV file.",
                 "Only rows for their assigned scope."),
     ]},
    {"key": "bulk", "label": "Bulk upload",
     "description": "The Excel template and the upload, review and import of many properties at once.",
     "actions": [
         _action("bulk.template", "Download template", "Download the Excel template for bulk upload."),
         _action("bulk.upload", "Upload", "Upload a filled template, review the rows and import them.",
                 "Only rows for their assigned scope."),
     ]},
    {"key": "documents", "label": "Documents",
     "description": "The document register: deeds, leases, plans and other documents, and their files.",
     "actions": [
         _action("documents.view", "View", "See the document register and a document's details.",
                 "Only documents of properties in their scope."),
         _action("documents.download", "Download", "Open, view and download attached files (deeds, leases, scans).",
                 "Only files of properties in their scope."),
         _action("documents.upload", "Upload", "Attach a new document and its file to a property.",
                 "Only to properties in their scope."),
         _action("documents.edit", "Edit", "Change a document's details: dates, reference, counterparty, amount.",
                 "Only documents they uploaded.", status="coming"),
         _action("documents.delete", "Delete", "Delete a document and its file.",
                 "Only documents they uploaded."),
     ]},
    {"key": "dashboard", "label": "Dashboard", "description": "Totals, charts and the business filters.",
     "actions": [
         _action("dashboard.view", "View", "See the dashboard, totals and charts, and filter them.",
                 "Only figures for their assigned scope."),
     ]},
    {"key": "alerts", "label": "Alerts & reminders",
     "description": "Documents expiring soon and the 3 / 6 / 9 / 12-month renewal ladder.",
     "actions": [
         _action("alerts.view", "View", "See expiry alerts (the bell) and renewal reminders.",
                 "Only alerts for their assigned scope."),
     ]},
    {"key": "types", "label": "Property types",
     "description": "What each property is used for (Educational, Warehouse ...), and each type's page.",
     "actions": [
         _action("types.view", "View", "See the property types and open a type's page."),
         _action("types.create", "Create", "Add a property type."),
         _action("types.edit", "Edit", "Rename a property type or change its code or colour."),
         _action("types.delete", "Delete", "Delete a property type (only when no property uses it)."),
     ]},
    {"key": "companies", "label": "Owning companies",
     "description": "The group companies holding title, and each company's page.",
     "actions": [
         _action("companies.view", "View", "See the owning companies and open a company's page."),
         _action("companies.create", "Create", "Add an owning company."),
         _action("companies.edit", "Edit", "Change a company's registered name, code or details."),
         _action("companies.delete", "Delete", "Delete an owning company (only when it owns no property)."),
     ]},
    {"key": "masters", "label": "Master sheets",
     "description": "Locations, location codes and the read-only system lists.",
     "actions": [
         _action("masters.view", "View", "See the master lists: locations, location codes and system lists."),
         _action("masters.create", "Create", "Add a location or location code."),
         _action("masters.edit", "Edit", "Change a location or location code."),
         _action("masters.delete", "Delete", "Delete a location or location code (only when nothing uses it)."),
     ]},
    {"key": "users", "label": "User & access management",
     "description": "Users, their roles and assigned scope, and the roles themselves.",
     "actions": [
         _action("users.view", "View users", "See the list of users and their roles.",
                 "Only people who share one of their assigned property types or companies."),
         _action("users.create", "Create users", "Give a new employee or manager access.",
                 "Cannot create Super Admins, or anyone who can manage roles."),
         _action("users.edit", "Edit users", "Change a user's role or scope, reset their password, sign them out.",
                 "Cannot change Super Admins, or anyone who can manage roles."),
         _action("users.deactivate", "Deactivate users", "Remove a user's access (kept for the audit trail).",
                 "Cannot deactivate Super Admins, or anyone who can manage roles."),
         _action("roles.manage", "Manage roles", "Change the roles and this access matrix."),
     ]},
    {"key": "system", "label": "System & audit", "description": "Audit log, backups and data clean-up.",
     "actions": [
         _action("audit.view", "View audit log", "See who changed what, and when."),
         _action("system.backup", "Backup & restore", "Back up the register and restore a backup.", status="coming"),
         _action("system.clear", "Clear data", "Remove test or old data in bulk (a backup is taken first).",
                 status="coming"),
     ]},
]

ACTIONS = {a["key"]: a for m in MODULES for a in m["actions"]}
ALL_KEYS = [a["key"] for m in MODULES for a in m["actions"]]

# The workbook's Permissions sheet: Super Admin, Administrator, Property Manager,
# Property Officer, Document Controller, Auditor, Viewer.
_MATRIX = """
properties.view    Y Y Y L Y Y Y
properties.create  Y Y Y Y N N N
properties.edit    Y Y L L N N N
properties.delete  Y Y N N N N N
properties.export  Y Y L N N Y N
bulk.template      Y Y Y Y N N N
bulk.upload        Y Y L N N N N
documents.view     Y Y Y L Y Y Y
documents.download Y Y Y L Y Y N
documents.upload   Y Y Y Y Y N N
documents.edit     Y Y Y L Y N N
documents.delete   Y Y L N L N N
dashboard.view     Y Y Y L Y Y Y
alerts.view        Y Y Y L Y Y Y
types.view         Y Y Y Y Y Y Y
types.create       Y Y N N N N N
types.edit         Y Y N N N N N
types.delete       Y N N N N N N
companies.view     Y Y Y Y Y Y Y
companies.create   Y Y N N N N N
companies.edit     Y Y N N N N N
companies.delete   Y N N N N N N
masters.view       Y Y Y Y Y Y Y
masters.create     Y Y Y N N N N
masters.edit       Y Y N N N N N
masters.delete     Y Y N N N N N
users.view         Y Y L N N N N
users.create       Y L N N N N N
users.edit         Y L N N N N N
users.deactivate   Y L N N N N N
roles.manage       Y N N N N N N
audit.view         Y Y N N N Y N
system.backup      Y N N N N N N
system.clear       Y N N N N N N
"""

DEFAULT_ROLES = [
    (SUPER_ADMIN, "Super Admin",
     "Owns the system. Full access to every module, including users, roles and settings. "
     "Held by one or two people, and not used for daily work."),
    ("ADMIN", "Administrator",
     "Runs the register day to day: all property data, master lists and bulk uploads. "
     "Manages users below Super Admin."),
    ("PROPERTY_MANAGER", "Property Manager",
     "Keeps their properties and documents complete and current, and can import them in bulk. "
     "Cannot delete properties."),
    ("PROPERTY_OFFICER", "Property Officer",
     "Adds properties and attaches documents within their scope. Cannot delete anything or export the register."),
    ("DOCUMENT_CONTROLLER", "Document Controller",
     "Looks after deeds, leases, plans and other documents for every property. Does not change property records."),
    ("AUDITOR", "Auditor", "Reads and exports everything to check it, including the audit log. Changes nothing."),
    ("VIEWER", "Viewer", "Sees the register, dashboard and alerts. Cannot download files, export or change anything."),
]


def default_levels():
    """{role code: {permission: level}} from the workbook matrix."""
    codes = [code for code, _, _ in DEFAULT_ROLES]
    out: Dict[str, Dict[str, str]] = {code: {} for code in codes}
    letters = {"Y": "yes", "L": "limited", "N": "no"}
    for line in _MATRIX.strip().splitlines():
        key, *marks = line.split()
        for code, mark in zip(codes, marks):
            out[code][key] = letters[mark]
    return out


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_roles(conn):
    """Give a register the workbook's roles once; after that they are edited in the app."""
    from . import db
    if db.was_seeded(conn, "roles"):
        return
    levels = default_levels()
    stamp = _now()
    for order, (code, name, description) in enumerate(DEFAULT_ROLES):
        if conn.execute("SELECT 1 FROM app_role WHERE code = ?", (code,)).fetchone():
            continue
        conn.execute("""INSERT INTO app_role (code, name, description, is_system, sort_order, created_at, updated_at)
                        VALUES (?, ?, ?, 1, ?, ?, ?)""", (code, name, description, order, stamp, stamp))
        for key, level in levels[code].items():
            if level != "no":
                conn.execute("INSERT INTO app_role_permission (role_code, permission, level) VALUES (?, ?, ?)",
                             (code, key, level))
    db.mark_seeded(conn, "roles")
    conn.commit()


def clean_level(key, level):
    """A level as stored: 'limited' only where the action defines what it means."""
    level = (level or "no").lower()
    if level not in LEVELS:
        raise ApiError("Unknown access level %r for %s." % (level, key))
    if level == "limited" and not ACTIONS[key]["limited"]:
        raise ApiError("%s can only be allowed or not, not limited." % _label(key))
    return level


def _label(key):
    module = next(m for m in MODULES if any(a["key"] == key for a in m["actions"]))
    return "%s: %s" % (module["label"], ACTIONS[key]["label"])


def role_levels(conn, code):
    """{permission: level} for every action, for one role."""
    if code == SUPER_ADMIN:
        return {key: "yes" for key in ALL_KEYS}
    levels = {key: "no" for key in ALL_KEYS}
    for row in conn.execute("SELECT permission, level FROM app_role_permission WHERE role_code = ?", (code,)):
        if row["permission"] in levels:
            levels[row["permission"]] = row["level"]
    return levels


def is_protected_role(levels, code):
    """Super Admins, and roles that can change the roles, are managed by Super Admins only."""
    return code == SUPER_ADMIN or levels.get("roles.manage") == "yes"


def user_scope(conn, user_id):
    types: List[int] = []
    companies: List[int] = []
    for row in conn.execute("SELECT kind, ref_id FROM app_user_scope WHERE user_id = ? ORDER BY ref_id",
                            (user_id,)):
        (types if row["kind"] == "type" else companies).append(row["ref_id"])
    return {"types": types, "companies": companies}


# --- the signed-in person's access -----------------------------------------------

class Access(object):
    """One request's view of what its signed-in person may do."""

    def __init__(self, user, levels, scope):
        self.user = user
        self.levels = levels
        self.types = list(scope["types"])
        self.companies = list(scope["companies"])

    @property
    def user_id(self):
        return self.user["id"]

    def level(self, key):
        return self.levels.get(key, "no")

    def can(self, key):
        return self.level(key) != "no"

    def best(self, keys):
        """The highest level among several actions."""
        return max((self.level(k) for k in keys), key=LEVELS.index)

    def require(self, key, message=None):
        if not self.can(key):
            raise ApiError(message or "You do not have access to do that. Ask your administrator.", 403)
        return self.level(key)

    def in_scope(self, sbu_id, entity_id):
        """Is a property of this type and owning company inside the person's scope?

        Both lists narrow: with types and companies assigned, a property must be of
        one of the types AND owned by one of the companies. Nothing assigned means
        nothing in scope.
        """
        if not self.types and not self.companies:
            return False
        if self.types and sbu_id not in self.types:
            return False
        if self.companies and entity_id not in self.companies:
            return False
        return True

    def scope_sql(self, alias="p"):
        """WHERE fragments restricting `alias` (a property) to the scope."""
        if not self.types and not self.companies:
            return ["1 = 0"], []
        where, params = [], []
        if self.types:
            where.append("%s.sbu_id IN (%s)" % (alias, ",".join("?" * len(self.types))))
            params.extend(self.types)
        if self.companies:
            where.append("%s.legal_entity_id IN (%s)" % (alias, ",".join("?" * len(self.companies))))
            params.extend(self.companies)
        return where, params

    def public(self):
        return {"permissions": dict(self.levels),
                "scope": {"types": self.types, "companies": self.companies}}


def load(conn, user):
    return Access(user, role_levels(conn, user["role"]), user_scope(conn, user["id"]))


def of(ctx):
    return getattr(ctx, "access", None)


def scope_for(ctx, *keys):
    """WHERE fragments for property alias `p` when the person's best level among
    `keys` is "limited"; nothing when it is "yes" (or there is no person)."""
    acc = of(ctx)
    if acc is None or acc.best(keys) != "limited":
        return [], []
    return acc.scope_sql("p")


def check_property(ctx, conn, key, property_id, write=False):
    """Refuse a property outside the person's scope when `key` is limited.

    Reading answers 404, as if the property were not there; changing answers 403.
    """
    acc = of(ctx)
    if acc is None or acc.level(key) != "limited":
        return
    row = conn.execute("SELECT sbu_id, legal_entity_id FROM property WHERE id = ?", (property_id,)).fetchone()
    if row is None:
        return      # the handler reports the missing property itself
    if not acc.in_scope(row["sbu_id"], row["legal_entity_id"]):
        if write:
            raise ApiError("This property is outside your assigned property types and companies.", 403)
        raise ApiError("Property not found.", 404)


def check_payload(ctx, key, sbu_id, entity_id):
    """Refuse saving a property into a type / company outside a limited person's scope."""
    acc = of(ctx)
    if acc is not None and acc.level(key) == "limited" and not acc.in_scope(sbu_id, entity_id):
        raise ApiError("You can only save properties of your assigned property types and companies.",
                       403, "sbu_id")


# --- which permission each route needs -------------------------------------------

SIGNED_IN = "signed-in"      # any signed-in person: their own account, and the session itself


def _sheet(action):
    """Master sheets: the property type and company sheets follow their own modules."""
    def pick(ctx):
        key = ctx.match.group("key")
        return {"sbu": "types", "legal_entity": "companies"}.get(key, "masters") + "." + action
    return pick


# handler ("module.function") -> a permission, a tuple of which any one will do,
# SIGNED_IN, or a function of the request returning one of those. A route that is
# missing here is refused (see tests/test_access.py, which checks they all are).
ROUTE_PERMISSIONS = {
    "api.get_reference": SIGNED_IN,
    "api.list_sbus": ("types.view", "properties.view", "dashboard.view", "documents.view"),
    "api.create_sbu": "types.create",
    "api.update_sbu": "types.edit",
    "api.delete_sbu": "types.delete",
    "api.list_legal_entities": ("companies.view", "properties.view", "dashboard.view", "documents.view"),
    "api.create_legal_entity": "companies.create",
    "api.update_legal_entity": "companies.edit",
    "api.delete_legal_entity": "companies.delete",
    "api.list_locations": ("masters.view", "properties.view"),
    "api.list_properties": "properties.view",
    "api.create_property": "properties.create",
    "api.get_property": "properties.view",
    "api.update_property": "properties.edit",
    "api.delete_property": "properties.delete",
    "api.list_documents": "documents.view",
    "api.create_document": "documents.upload",
    "api.list_all_documents": "documents.view",
    "api.download_document": "documents.download",
    "api.get_document": "documents.view",
    "api.delete_document": "documents.delete",
    "api.get_stats": ("dashboard.view", "alerts.view"),
    "api.export_properties_csv": "properties.export",
    "masters.list_sheets": ("masters.view", "types.view", "companies.view"),
    "masters.get_sheet": _sheet("view"),
    "masters.create_row": _sheet("create"),
    "masters.update_row": _sheet("edit"),
    "masters.delete_row": _sheet("delete"),
    "bulk.download_template": "bulk.template",
    "bulk.upload_properties": "bulk.upload",
    "auth.get_status": SIGNED_IN,
    "auth.login": SIGNED_IN,
    "auth.logout": SIGNED_IN,
    "auth.setup": SIGNED_IN,
    "admin.change_own_password": SIGNED_IN,
    "admin.list_users": "users.view",
    "admin.get_user": "users.view",
    "admin.create_user": "users.create",
    "admin.update_user": ("users.edit", "users.deactivate"),
    "admin.reset_password": "users.edit",
    "admin.revoke_sessions": "users.edit",
    "admin.unlock_user": "users.edit",
    "admin.list_roles": ("users.view", "roles.manage"),
    "admin.create_role": "roles.manage",
    "admin.update_role": "roles.manage",
    "admin.delete_role": "roles.manage",
    "admin.list_audit": "audit.view",
}


def handler_key(handler):
    return "%s.%s" % (handler.__module__.rsplit(".", 1)[-1], handler.__name__)


def check_route(ctx, handler):
    """Raise 403 unless the signed-in person may call this handler."""
    need = ROUTE_PERMISSIONS.get(handler_key(handler))
    if need is None:
        raise ApiError("This endpoint has no access rule, so it is closed.", 403)
    if callable(need):
        need = need(ctx)
    if need == SIGNED_IN:
        return
    acc = of(ctx)
    keys = need if isinstance(need, tuple) else (need,)
    if acc is None or not any(acc.can(k) for k in keys):
        raise ApiError("You do not have access to this. Ask your administrator if you need it.", 403)


# --- the audit log --------------------------------------------------------------

def record(conn, action, target="", detail="", user=None, ip=None, commit=True):
    """Add one line to the audit log. `user` is the person acting, if anyone."""
    conn.execute(
        """INSERT INTO audit_log (at, user_id, user_name, user_email, action, target, detail, ip)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (_now(), user["id"] if user else None, user["name"] if user else None,
         user["email"] if user else None, action, (target or "")[:300], (detail or "")[:2000], ip))
    if commit:
        conn.commit()


# What each successful change is logged as, when its handler did not say more.
_AUDIT_ACTIONS = {
    "api.create_sbu": ("type.create", "Added property type"),
    "api.update_sbu": ("type.update", "Changed property type"),
    "api.delete_sbu": ("type.delete", "Deleted property type"),
    "api.create_legal_entity": ("company.create", "Added owning company"),
    "api.update_legal_entity": ("company.update", "Changed owning company"),
    "api.delete_legal_entity": ("company.delete", "Deleted owning company"),
    "api.create_property": ("property.create", "Added property"),
    "api.update_property": ("property.update", "Changed property"),
    "api.delete_property": ("property.delete", "Deleted property"),
    "api.create_document": ("document.upload", "Attached document"),
    "api.delete_document": ("document.delete", "Deleted document"),
    "masters.create_row": ("master.create", "Added master row"),
    "masters.update_row": ("master.update", "Changed master row"),
    "masters.delete_row": ("master.delete", "Deleted master row"),
    "bulk.upload_properties": ("bulk.import", "Imported properties"),
}


def _describe(payload):
    if not isinstance(payload, dict):
        return ""
    code = payload.get("property_code") or payload.get("code") or payload.get("short_code")
    name = payload.get("name") or payload.get("title")
    return " · ".join(str(x) for x in (code, name) if x)


def audit_request(conn, ctx, handler, status, payload):
    """Log a successful change made through the API (reads are not logged)."""
    key = handler_key(handler)
    if key not in _AUDIT_ACTIONS or status >= 400:
        return
    if key == "bulk.upload_properties" and not (payload or {}).get("created"):
        return      # a check-only upload changes nothing
    action, verb = _AUDIT_ACTIONS[key]
    explicit = getattr(ctx, "audit_target", None)
    target = explicit or _describe(payload) or ctx.handler.path.split("?")[0]
    detail = getattr(ctx, "audit_detail", None) or ""
    if key == "bulk.upload_properties":
        detail = "%d properties: %s" % (len(payload["created"]), ", ".join(payload["created"][:50]))
        target = "Bulk upload"
    if key.startswith("masters."):
        verb = "%s (%s)" % (verb, ctx.match.group("key"))
    record(conn, action, target, detail or verb, ctx.user, client_ip(ctx))


def client_ip(ctx):
    handler = getattr(ctx, "handler", None)
    return handler.client_address[0] if handler is not None and handler.client_address else None


SLUG = re.compile(r"[^A-Z0-9]+")


def role_code_for(name):
    return SLUG.sub("_", (name or "").upper()).strip("_")[:40]
