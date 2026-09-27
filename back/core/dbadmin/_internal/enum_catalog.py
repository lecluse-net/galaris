"""Read-only admission checks for the enum replacement operations we support."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..contracts import DbAdminFatalError, EnumTransition


@dataclass(frozen=True, slots=True)
class EnumColumn:
    table_name: str
    column_name: str
    has_default: bool
    default_value: str | None


@dataclass(frozen=True, slots=True)
class EnumGrant:
    role: str | None  # None denotes PUBLIC, not a role literally named PUBLIC.
    grant_option: bool


@dataclass(frozen=True, slots=True)
class EnumReplacement:
    columns: tuple[EnumColumn, ...]
    owner: str
    grants: tuple[EnumGrant, ...]
    comment: str | None


async def inspect_replacement(
    connection: AsyncConnection, transition: EnumTransition, *, injective: bool,
) -> EnumReplacement:
    """Reject dependencies we cannot rebuild without changing their semantics.

    Inspect pg_catalog rather than information_schema: the latter can hide objects
    from the migration role. Do not evaluate defaults (they may have side effects).
    """

    params = {"name": transition.name, "injective": injective}
    info = (await connection.execute(text(
        "SELECT t.oid, t.typarray, pg_get_userbyid(t.typowner) AS owner, "
        "(has_schema_privilege(current_user, n.oid, 'CREATE') AND "
        "has_schema_privilege(current_user, n.oid, 'USAGE')) AS can_create, "
        "pg_has_role(current_user, t.typowner, 'SET') AS can_restore_owner, "
        "(has_schema_privilege(t.typowner, n.oid, 'CREATE') OR "
        "EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolsuper)) AS owner_can_create, "
        "obj_description(t.oid, 'pg_type') AS comment "
        "FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
        "WHERE n.nspname='public' AND t.typname=:name"
    ), params)).one()
    if not info.can_create or not info.can_restore_owner or not info.owner_can_create:
        raise DbAdminFatalError(
            f"Enum public.{transition.name} replacement requires CREATE on public and "
            f"the ability to restore owner {info.owner!r} (SET ROLE and owner schema CREATE)."
        )

    # The automatic array type is allowed, but its consumers are not. Likewise
    # functions, domains, views, foreign tables and cross-schema columns must not
    # be discovered only when DROP TYPE fails after a business action has committed.
    blocked = (await connection.execute(text(
        "SELECT pg_describe_object(d.classid,d.objid,d.objsubid) "
        "FROM pg_depend d "
        "LEFT JOIN pg_class c ON d.classid='pg_class'::regclass AND c.oid=d.objid "
        "LEFT JOIN pg_namespace n ON n.oid=c.relnamespace "
        "LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=d.objsubid "
        "LEFT JOIN pg_attrdef ad ON d.classid='pg_attrdef'::regclass AND ad.oid=d.objid "
        "LEFT JOIN pg_attribute da ON da.attrelid=ad.adrelid AND da.attnum=ad.adnum "
        "LEFT JOIN pg_class dc ON dc.oid=ad.adrelid "
        "LEFT JOIN pg_namespace dn ON dn.oid=dc.relnamespace "
        "WHERE d.refclassid='pg_type'::regclass AND d.refobjid IN (:oid,:array) "
        "AND NOT (d.classid='pg_type'::regclass AND d.objid=:array) "
        "AND NOT COALESCE((c.relkind='r' AND n.nspname='public' AND a.atttypid=:oid "
        "AND a.attnum>0 AND NOT a.attisdropped) OR "
        "(dc.relkind='r' AND dn.nspname='public' AND da.atttypid=:oid "
        "AND da.attgenerated=''), false) ORDER BY 1"
    ), {"oid": info.oid, "array": info.typarray})).scalars().all()
    if blocked:
        raise DbAdminFatalError(
            f"Enum public.{transition.name} has unsupported dependency: " + "; ".join(map(str, blocked))
        )

    rows = (await connection.execute(text(
        "SELECT c.relname, a.attname, pg_has_role(current_user,c.relowner,'USAGE') AS can_alter, "
        "pg_get_userbyid(c.relowner) AS owner, a.attgenerated::text AS generated, "
        "EXISTS (SELECT 1 FROM pg_inherits i WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS inherited, "
        "ad.oid IS NOT NULL AS has_default, pg_get_expr(ad.adbin,ad.adrelid) AS expression, "
        "'NULL::' || format_type(a.atttypid,NULL) AS null_expression, "
        "(SELECT e.enumlabel FROM pg_enum e WHERE e.enumtypid=a.atttypid AND "
        "(pg_get_expr(ad.adbin,ad.adrelid)=quote_literal(e.enumlabel)||'::'||format_type(a.atttypid,NULL) OR "
        "(current_setting('standard_conforming_strings')='on' AND "
        "pg_get_expr(ad.adbin,ad.adrelid)=chr(39)||replace(e.enumlabel,chr(39),chr(39)||chr(39))||chr(39)|| "
        "'::'||format_type(a.atttypid,NULL)))) AS default_value "
        "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "LEFT JOIN pg_attrdef ad ON ad.adrelid=c.oid AND ad.adnum=a.attnum "
        "WHERE a.atttypid=:oid AND a.attnum>0 AND NOT a.attisdropped "
        "AND c.relkind='r' AND n.nspname='public' ORDER BY c.relname,a.attnum"
    ), {"oid": info.oid})).all()
    columns: list[EnumColumn] = []
    for row in rows:
        key = f"public.{row.relname}.{row.attname}"
        if not row.can_alter:
            raise DbAdminFatalError(f"Enum public.{transition.name}: cannot alter {key}, owned by {row.owner!r}")
        if row.inherited or row.generated:
            raise DbAdminFatalError(f"Enum public.{transition.name}: unsupported inherited/generated dependency {key}")
        if row.has_default and row.default_value is None and row.expression != row.null_expression:
            raise DbAdminFatalError(f"Enum public.{transition.name}: unsupported default dependency on {key}; use a constant enum default")
        columns.append(EnumColumn(str(row.relname), str(row.attname), bool(row.has_default),
                                  str(row.default_value) if row.default_value is not None else None))

    # Column dependencies can block ALTER TABLE even without a direct dependency
    # on the enum (a view selecting state::text, a foreign key, a generated column).
    blocked = (await connection.execute(text(
        "SELECT DISTINCT pg_describe_object(d.classid,d.objid,d.objsubid) "
        "FROM pg_attribute a JOIN pg_depend d ON d.refclassid='pg_class'::regclass "
        "AND d.refobjid=a.attrelid AND d.refobjsubid=a.attnum "
        "LEFT JOIN pg_index ix ON d.classid='pg_class'::regclass AND ix.indexrelid=d.objid "
        "LEFT JOIN pg_constraint co ON d.classid='pg_constraint'::regclass AND co.oid=d.objid "
        "LEFT JOIN pg_attrdef ad ON d.classid='pg_attrdef'::regclass AND ad.oid=d.objid "
        "WHERE a.atttypid=:oid AND a.attnum>0 AND NOT a.attisdropped "
        "AND NOT COALESCE((ix.indexrelid IS NOT NULL AND ix.indexprs IS NULL AND ix.indpred IS NULL "
        "AND (NOT ix.indisunique OR :injective)) OR "
        "(co.contype IN ('p','u') AND :injective) OR "
        "(ad.adrelid=a.attrelid AND ad.adnum=a.attnum AND a.attgenerated=''),false) ORDER BY 1"
    ), {"oid": info.oid, "injective": injective})).scalars().all()
    if blocked:
        raise DbAdminFatalError(f"Enum public.{transition.name} has unsupported column dependency: " + "; ".join(map(str, blocked)))

    grants = (await connection.execute(text(
        "SELECT CASE WHEN acl.grantee=0 THEN NULL ELSE pg_get_userbyid(acl.grantee) END AS role, "
        "acl.is_grantable, acl.grantor=t.typowner AS owner_grant "
        "FROM pg_type t, LATERAL aclexplode(COALESCE(t.typacl,acldefault('T',t.typowner))) acl "
        "WHERE t.oid=:oid"
    ), {"oid": info.oid})).all()
    if any(not row.owner_grant for row in grants):
        raise DbAdminFatalError(f"Enum public.{transition.name} has delegated grants; consolidate grants under its owner before replacement")
    return EnumReplacement(tuple(columns), str(info.owner),
                           tuple(EnumGrant(str(row.role) if row.role is not None else None, bool(row.is_grantable)) for row in grants),
                           str(info.comment) if info.comment is not None else None)
