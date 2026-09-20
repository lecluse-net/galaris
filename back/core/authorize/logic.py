from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger

from core.user.models import User
from core.authorize import Assignment, Role
from .context import role_id_ctx

from typing import List, Union, Optional

async def check_privilege(user: Optional[User], privilege_code: Union[str, List[str]], db: AsyncSession, role_id: Optional[int] = None) -> bool:
    """
    Checks if the user has the specified privilege code(s) for the current role.
    
    Handles special privileges:
    - "user": Any authenticated active user has this privilege automatically
    - "guest": Any non-authenticated user has this privilege automatically
    
    Args:
        user: The user to check.
        privilege_code: A single code (str) or a list of codes (List[str]).
        db: Database session.
        role_id: Optional role ID to check. If not provided, uses the role from context.
        
    Returns:
        bool:
        - If privilege_code is str: True if user has it.
        - If privilege_code is List[str]: True if user has AT LEAST ONE of them (OR logic).
    """
    # Build the effective privileges set
    effective_privileges: set[str] = set()
    
    # Add special privilege based on authentication status
    if user is None:
        effective_privileges.add("guest")
    elif user.is_active:
        effective_privileges.add("user")
    
    # If user is active, add privileges from their assignments
    if user is not None and user.is_active:
        # Get the current role_id from context if not provided
        if role_id is None:
            role_id = role_id_ctx.get()
        
        if role_id is None:
            # Load all assignments with Roles and Privileges
            stmt = (
                select(Assignment)
                .where(Assignment.user_id == user.id)
                .options(
                    selectinload(Assignment.role).selectinload(Role.privileges)
                )
            )
            result = await db.execute(stmt)
            assignments = result.scalars().all()
            
            for assignment in assignments:
                if assignment.role and assignment.role.privileges:
                    for priv in assignment.role.privileges:
                        effective_privileges.add(priv.code)
        else:
            # Load only the specific assignment for the current role
            stmt = (
                select(Assignment)
                .where(Assignment.user_id == user.id)
                .where(Assignment.role_id == role_id)
                .options(
                    selectinload(Assignment.role).selectinload(Role.privileges)
                )
            )
            result = await db.execute(stmt)
            assignment = result.scalar_one_or_none()
            
            if assignment and assignment.role and assignment.role.privileges:
                for priv in assignment.role.privileges:
                    effective_privileges.add(priv.code)
    
    # Check if requested privilege is in effective privileges
    if isinstance(privilege_code, list):
        is_allowed = any(code in effective_privileges for code in privilege_code)
    else:
        is_allowed = privilege_code in effective_privileges
    
    if not is_allowed and user is not None:
        logger.debug(f"User {user.email} denied access to {privilege_code}. Has: {effective_privileges}")
    
    return is_allowed
