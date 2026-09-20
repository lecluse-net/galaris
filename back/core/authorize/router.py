from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from typing import List

from core.database import get_db
from core.i18n import tr
from core.user import notify_user_access_changed, user_service
from .context import role_id_ctx
from .admin_guard import AdministratorConflictError, preserve_administrator, preserve_admin_role
from .models import Privilege, Role, Assignment, PrivilegeList, RolePrivilege
from .schemas import (
    Privilege as PrivilegeSchema,
    PrivilegeCreate,
    Role as RoleSchema,
    RoleCreate,
    RoleUpdate,
    RoleWithPrivileges,
    Assignment as AssignmentSchema,
    AssignmentCreate,
    AssignmentWithRole,
    AssignmentsPaginated,
    RolePrivilegeAction,
    SwitchRoleRequest,
    PrivilegeList as PrivilegeListSchema,
    PrivilegeListCreate,
    PrivilegeListUpdate,
    PrivilegeListAction
)
from core.user.auth_service import create_access_token_for_user
from core.user import Token
from .assertions import OwnUserOrPrivilegeAssertion
from .decorators import authorize
from .definitions import Privileges


router = APIRouter(prefix="/authorize", tags=["authorization"])


async def _detail(key: str) -> str:
    return await tr(f"authorize_api.errors.{key}")


async def _guard_admin(*, role: Role | None = None, assignment_id: int | None = None) -> None:
    try:
        if role is not None:
            await preserve_admin_role(role)
        if assignment_id is not None:
            await preserve_administrator(assignment_id=assignment_id)
    except AdministratorConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ==================== Privileges ====================

@router.get("/privileges", response_model=List[PrivilegeSchema])
@authorize(privileges=[Privileges.READ_PRIVILEGE, Privileges.MANAGE_PRIVILEGE])
async def list_privileges(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Privilege))
    return result.scalars().all()


@router.get("/my-privileges", response_model=List[str])
@authorize(privileges=[])  # Any authenticated user can access their own privileges
async def get_my_privileges(db: AsyncSession = Depends(get_db)) -> List[str]:
    """
    Get the list of privilege codes for the current user's active role.
    Returns an empty list if no role is active.
    """
    role_id = role_id_ctx.get()
    
    if not role_id:
        return []
    
    # Get privileges for the current role
    result = await db.execute(
        select(Privilege.code)
        .join(RolePrivilege)
        .where(RolePrivilege.role_id == role_id)
    )
    
    privilege_codes = result.scalars().all()
    return list(privilege_codes)


@router.post("/privileges", response_model=PrivilegeSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.MANAGE_PRIVILEGE)
async def create_privilege(
    privilege: PrivilegeCreate,
    db: AsyncSession = Depends(get_db)
):
    # Check if code already exists
    existing = await db.execute(select(Privilege).where(Privilege.code == privilege.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=await _detail("privilege_code_exists"))
    
    new_privilege = Privilege(**privilege.model_dump())
    db.add(new_privilege)
    await db.commit()
    await db.refresh(new_privilege)
    return new_privilege


@router.delete("/privileges/{id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.MANAGE_PRIVILEGE)
async def delete_privilege(
    id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Privilege).where(Privilege.id == id))
    privilege = result.scalar_one_or_none()
    if not privilege:
        raise HTTPException(status_code=404, detail=await _detail("privilege_not_found"))
    
    admin_role = await db.scalar(
        select(Role).join(RolePrivilege, RolePrivilege.role_id == Role.id)
        .where(RolePrivilege.privilege_id == id, Role.code == "admin")
    )
    if admin_role is not None:
        await _guard_admin(role=admin_role)
    await db.delete(privilege)
    await db.commit()
    return None


# ==================== Roles ====================

@router.get("/roles", response_model=List[RoleWithPrivileges])
@authorize(privileges=[Privileges.READ_ROLE, Privileges.MANAGE_ROLE])
async def list_roles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Role).options(selectinload(Role.privileges)))
    return result.scalars().unique().all()


@router.get("/roles/{id}", response_model=RoleWithPrivileges)
@authorize(privileges=[Privileges.READ_ROLE, Privileges.MANAGE_ROLE])
async def get_role(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Role).where(Role.id == id).options(selectinload(Role.privileges))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=await _detail("role_not_found"))
    return role


@router.post("/roles", response_model=RoleSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.MANAGE_ROLE)
async def create_role(
    role: RoleCreate,
    db: AsyncSession = Depends(get_db)
):
    # Check if code already exists
    existing = await db.execute(select(Role).where(Role.code == role.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=await _detail("role_code_exists"))
    
    new_role = Role(**role.model_dump())
    db.add(new_role)
    await db.commit()
    await db.refresh(new_role)
    return new_role


@router.put("/roles/{id}", response_model=RoleSchema)
@authorize(privileges=Privileges.MANAGE_ROLE)
async def update_role(
    id: int,
    role_update: RoleUpdate,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Role).where(Role.id == id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=await _detail("role_not_found"))
    
    update_data = role_update.model_dump(exclude_unset=True)
    if "code" in update_data and update_data["code"] != role.code:
        await _guard_admin(role=role)
    for key, value in update_data.items():
        setattr(role, key, value)
    
    await db.commit()
    await db.refresh(role)
    return role


@router.delete("/roles/{id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.MANAGE_ROLE)
async def delete_role(
    id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Role).where(Role.id == id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=await _detail("role_not_found"))
    
    await _guard_admin(role=role)
    await db.delete(role)
    await db.commit()
    await notify_user_access_changed()
    return None


# ==================== Role Privileges ====================

@router.post("/roles/{role_id}/privileges", response_model=RoleWithPrivileges)
@authorize(privileges=Privileges.MANAGE_ROLE)
async def add_privileges_to_role(
    role_id: int,
    action: RolePrivilegeAction,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Role).where(Role.id == role_id).options(selectinload(Role.privileges))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=await _detail("role_not_found"))
    
    # Get privileges to add
    priv_result = await db.execute(
        select(Privilege).where(Privilege.id.in_(action.privilege_ids))
    )
    privileges = priv_result.scalars().all()
    
    # Add privileges that aren't already assigned
    for priv in privileges:
        if priv not in role.privileges:
            role.privileges.append(priv)
    
    await db.commit()
    await db.refresh(role)
    await notify_user_access_changed()
    return role


@router.delete("/roles/{role_id}/privileges", response_model=RoleWithPrivileges)
@authorize(privileges=Privileges.MANAGE_ROLE)
async def remove_privileges_from_role(
    role_id: int,
    action: RolePrivilegeAction,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Role).where(Role.id == role_id).options(selectinload(Role.privileges))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=await _detail("role_not_found"))
    
    # Remove specified privileges
    if action.privilege_ids:
        await _guard_admin(role=role)
    role.privileges = [p for p in role.privileges if p.id not in action.privilege_ids]
    
    await db.commit()
    await db.refresh(role)
    await notify_user_access_changed()
    return role


# ==================== Assignments ====================

@router.get("/assignments", response_model=AssignmentsPaginated)
@authorize(privileges=[Privileges.READ_ASSIGNMENT, Privileges.MANAGE_ASSIGNMENT])
async def list_assignments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    # Get total count
    count_query = select(func.count()).select_from(Assignment)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Get items
    query = (
        select(Assignment)
        .options(
            selectinload(Assignment.role),
            selectinload(Assignment.user)
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    return AssignmentsPaginated(
        items=[AssignmentWithRole.model_validate(a) for a in items],
        total=total,
    )


@router.get("/users/{user_id}/assignments", response_model=List[AssignmentWithRole])
@authorize(
    privileges=["user", Privileges.MANAGE_ASSIGNMENT],
    assertion=OwnUserOrPrivilegeAssertion,
    params={
        "owner_param": "user_id",
        "fallback_privilege": Privileges.MANAGE_ASSIGNMENT,
    },
)
async def get_user_assignments(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Assignment)
        .where(Assignment.user_id == user_id)
        .options(
            selectinload(Assignment.role),
            selectinload(Assignment.user)
        )
    )
    return result.scalars().all()


@router.post("/assignments", response_model=AssignmentSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.MANAGE_ASSIGNMENT)
async def create_assignment(
    assignment: AssignmentCreate,
    db: AsyncSession = Depends(get_db)
):
    # Check if assignment already exists
    existing = await db.execute(
        select(Assignment).where(
            Assignment.user_id == assignment.user_id,
            Assignment.role_id == assignment.role_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=await _detail("assignment_exists"))
    
    new_assignment = Assignment(**assignment.model_dump())
    db.add(new_assignment)
    await db.commit()
    await db.refresh(new_assignment)
    await notify_user_access_changed(new_assignment.user_id)
    return new_assignment


@router.delete("/assignments/{id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.MANAGE_ASSIGNMENT)
async def delete_assignment(
    id: int,
    db: AsyncSession = Depends(get_db)
):
    await _guard_admin(assignment_id=id)
    result = await db.execute(select(Assignment).where(Assignment.id == id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail=await _detail("assignment_not_found"))
    
    user_id = assignment.user_id
    await db.delete(assignment)
    await db.commit()
    await notify_user_access_changed(user_id)
    return None


# ==================== Context Switching ====================

@router.post("/switch-role", response_model=Token)
@authorize(privileges=[])  # Any authenticated user can switch their own role
async def switch_role(
    request: SwitchRoleRequest,
    db: AsyncSession = Depends(get_db)
):
    current_user = await user_service.get_current_user()
    if not current_user:
         raise HTTPException(
             status_code=status.HTTP_401_UNAUTHORIZED,
             detail=await _detail("not_authenticated"),
         )

    # Verify assignment
    result = await db.execute(
        select(Assignment, Role)
        .join(Role)
        .where(Assignment.user_id == current_user.id)
        .where(Assignment.role_id == request.role_id)
    )
    assignment_row = result.first()
    
    if not assignment_row:
         raise HTTPException(status_code=403, detail=await _detail("role_not_owned"))
    
    access_token = await create_access_token_for_user(
        current_user,
        db,
        role_id=request.role_id,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.put("/assignments/{id}/default", response_model=AssignmentSchema)
@authorize(privileges=[])
async def set_default_assignment(
    id: int,
    db: AsyncSession = Depends(get_db)
):
    current_user = await user_service.get_current_user()
    if not current_user:
         raise HTTPException(
             status_code=status.HTTP_401_UNAUTHORIZED,
             detail=await _detail("not_authenticated"),
         )

    # Get assignment and check ownership
    result = await db.execute(select(Assignment).where(Assignment.id == id))
    target_assignment = result.scalar_one_or_none()
    
    if not target_assignment:
        raise HTTPException(status_code=404, detail=await _detail("assignment_not_found"))
    
    if target_assignment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail=await _detail("own_assignments_only"))
    
    # Reset all user assignments default
    await db.execute(
        select(Assignment)
        .where(Assignment.user_id == current_user.id)
        .execution_options(synchronize_session=False)
    )
    # The above is just a select, we need to update. 
    # Better approach:
    # 1. Update all user assignments to is_default = False
    # 2. Update target to is_default = True
    
    # We can iterate or do bulk update but iterating is safe for session sync usually or separate statements.
    
    # Get all assignments for user
    user_assignments_result = await db.execute(
        select(Assignment).where(Assignment.user_id == current_user.id)
    )
    user_assignments = user_assignments_result.scalars().all()
    
    for assignment in user_assignments:
        assignment.is_default = (assignment.id == id)
        
    await db.commit()
    await db.refresh(target_assignment)
    return target_assignment


# ==================== Privilege Lists ====================

@router.get("/privilege-lists", response_model=List[PrivilegeListSchema])
@authorize(privileges=[Privileges.READ_PRIVILEGE, Privileges.MANAGE_PRIVILEGE])
async def list_privilege_lists(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PrivilegeList)
        .options(selectinload(PrivilegeList.privileges))
        .order_by(PrivilegeList.display_name)
    )
    return result.scalars().unique().all()


@router.post("/privilege-lists", response_model=PrivilegeListSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.MANAGE_PRIVILEGE)
async def create_privilege_list(
    item: PrivilegeListCreate,
    db: AsyncSession = Depends(get_db)
):
    existing = await db.execute(select(PrivilegeList).where(PrivilegeList.display_name == item.display_name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=await _detail("list_exists"))
    
    new_list = PrivilegeList(**item.model_dump())
    db.add(new_list)
    await db.flush()
    # Capture ID before commit to avoid expiration issues
    new_id = new_list.id
    new_name = new_list.display_name
    await db.commit()
    
    return PrivilegeListSchema(
        id=new_id,
        display_name=new_name,
        privileges=[]
    )


@router.put("/privilege-lists/{id}", response_model=PrivilegeListSchema)
@authorize(privileges=Privileges.MANAGE_PRIVILEGE)
async def update_privilege_list(
    id: int,
    item_update: PrivilegeListUpdate,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(PrivilegeList).where(PrivilegeList.id == id).options(selectinload(PrivilegeList.privileges)))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=await _detail("list_not_found"))
    
    update_data = item_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/privilege-lists/{id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.MANAGE_PRIVILEGE)
async def delete_privilege_list(
    id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(PrivilegeList).where(PrivilegeList.id == id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=await _detail("list_not_found"))
    
    # Explicitly unassign privileges (though ondelete="SET NULL" should handle DB side)
    # This ensures session is aware
    stmt = update(Privilege).where(Privilege.privilege_list_id == id).values(privilege_list_id=None)
    await db.execute(stmt)
    
    await db.delete(item)
    await db.commit()
    return None


@router.post("/privilege-lists/{id}/privileges", response_model=PrivilegeListSchema)
@authorize(privileges=Privileges.MANAGE_PRIVILEGE)
async def add_privileges_to_list(
    id: int,
    action: PrivilegeListAction,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(PrivilegeList).where(PrivilegeList.id == id).options(selectinload(PrivilegeList.privileges)))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=await _detail("list_not_found"))
    
    # 1-to-N: We set the privilege_list_id on the privileges
    # This effectively moves them from any other list they were in.
    priv_result = await db.execute(select(Privilege).where(Privilege.id.in_(action.privilege_ids)))
    privileges = priv_result.scalars().all()
    
    for priv in privileges:
        priv.privilege_list_id = item.id
            
    await db.commit()
    
    # Re-fetch with eager load to avoid MissingGreenlet
    result = await db.execute(
        select(PrivilegeList)
        .where(PrivilegeList.id == id)
        .options(selectinload(PrivilegeList.privileges))
    )
    return result.scalar_one()


@router.delete("/privilege-lists/{id}/privileges", response_model=PrivilegeListSchema)
@authorize(privileges=Privileges.MANAGE_PRIVILEGE)
async def remove_privileges_from_list(
    id: int,
    action: PrivilegeListAction,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(PrivilegeList).where(PrivilegeList.id == id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=await _detail("list_not_found"))
    
    # 1-to-N: We set privilege_list_id to Null for those in this list
    priv_result = await db.execute(select(Privilege).where(Privilege.id.in_(action.privilege_ids)).where(Privilege.privilege_list_id == id))
    privileges = priv_result.scalars().all()

    for priv in privileges:
        priv.privilege_list_id = None
    
    await db.commit()
    
    # Re-fetch with eager load
    result = await db.execute(
        select(PrivilegeList)
        .where(PrivilegeList.id == id)
        .options(selectinload(PrivilegeList.privileges))
    )
    return result.scalar_one()
