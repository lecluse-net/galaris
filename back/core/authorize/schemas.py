from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional


# Privilege schemas
class PrivilegeBase(BaseModel):
    code: str = Field(..., max_length=100)
    display_name: Optional[str] = Field(default=None, max_length=255)
    privilege_list_id: Optional[int] = None


class PrivilegeListBase(BaseModel):
    display_name: str = Field(..., max_length=255)


class PrivilegeListCreate(PrivilegeListBase):
    pass


class PrivilegeList(PrivilegeListBase):
    id: int
    privileges: List['Privilege'] = []

    model_config = ConfigDict(from_attributes=True)


class PrivilegeListUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=255)


class PrivilegeListAction(BaseModel):
    privilege_ids: List[int]


class PrivilegeCreate(PrivilegeBase):
    pass


class Privilege(PrivilegeBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# Role schemas
class RoleBase(BaseModel):
    code: str = Field(..., max_length=100)
    display_name: Optional[str] = Field(default=None, max_length=150)


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    code: Optional[str] = Field(default=None, max_length=100)
    display_name: Optional[str] = Field(default=None, max_length=150)


class Role(RoleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class RoleWithPrivileges(Role):
    privileges: List[Privilege] = []


# Assignment schemas
class AssignmentBase(BaseModel):
    user_id: int
    role_id: int
    is_default: bool = False


class AssignmentCreate(AssignmentBase):
    pass


class Assignment(AssignmentBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


from core.user import User as UserSchema

class AssignmentWithRole(Assignment):
    role: Role
    user: UserSchema


class AssignmentsPaginated(BaseModel):
    items: List[AssignmentWithRole]
    total: int


# Role-Privilege management
class RolePrivilegeAction(BaseModel):
    privilege_ids: List[int]


class SwitchRoleRequest(BaseModel):
    role_id: int
