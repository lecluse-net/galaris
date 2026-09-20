"""Simplified Chinese user and authentication messages."""

default = {
    "user_api": {
        "logged_out": "已成功退出登录",
        "errors": {
            "last_administrator": "移除此访问权限前，请保留至少一位处于启用状态的管理员。",
            "protected_admin_role": "无法删除或重命名内置管理员角色，也无法移除其权限。",
            "account_in_use": "此账户仍拥有资源，包括已归档的智能体。请先重新分配这些资源，再删除账户。",
            "incorrect_credentials": "电子邮箱或密码错误",
            "account_disabled": "您的账户已被停用",
            "account_locked": "失败次数过多，请稍后重试",
            "mfa_required": "请输入身份验证码",
            "invalid_mfa_code": "身份验证码无效或已使用",
            "invalid_or_expired_token": "令牌无效或已过期",
            "malformed_token": "令牌格式错误：缺少电子邮箱",
            "user_not_found": "未找到用户",
            "not_authenticated": "尚未通过身份验证",
            "registration_closed": "公开注册已关闭",
            "token_not_found": "未找到令牌",
            "email_registered": "电子邮箱已注册：${email}",
            "email_in_use": "电子邮箱已被使用：${email}",
            "avatar_not_found": "未找到头像",
            "invalid_avatar_type": "不支持此头像类型。允许的类型：${types}",
            "invalid_avatar_content": "所选文件不是有效的受支持图片",
            "avatar_too_large": "头像大小不得超过 5 MB",
        },
    },
}
