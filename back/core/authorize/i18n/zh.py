"""Simplified Chinese authorization API messages."""

default = {
    "authorize_api": {
        "errors": {
            "privilege_code_exists": "权限代码已存在",
            "privilege_not_found": "未找到权限",
            "role_code_exists": "角色代码已存在",
            "role_not_found": "未找到角色",
            "assignment_exists": "角色分配已存在",
            "assignment_not_found": "未找到角色分配",
            "not_authenticated": "尚未通过身份验证",
            "route_not_declared": "未配置路由授权",
            "inactive_user": "用户未启用",
            "missing_privilege": "缺少权限：${privileges}",
            "assertion_denied": "断言规则拒绝访问",
            "role_not_owned": "您没有此角色",
            "own_assignments_only": "您只能修改自己的角色分配",
            "list_exists": "同名列表已存在",
            "list_not_found": "未找到列表",
        },
    },
}
