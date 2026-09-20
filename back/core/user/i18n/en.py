"""English user and authentication messages."""

default = {
    "user_api": {
        "logged_out": "Logged out successfully",
        "errors": {
            "last_administrator": "Keep at least one active administrator before removing this access.",
            "protected_admin_role": "The built-in administrator role and its privileges cannot be removed or renamed.",
            "account_in_use": "This account still owns resources, including archived agents. Reassign them before deleting it.",
            "incorrect_credentials": "Incorrect email or password",
            "account_disabled": "Your account has been disabled",
            "account_locked": "Too many failed attempts. Try again later",
            "mfa_required": "Enter your authentication code",
            "invalid_mfa_code": "Invalid or already used authentication code",
            "invalid_or_expired_token": "Invalid or expired token",
            "malformed_token": "Malformed token: missing email",
            "user_not_found": "User not found",
            "not_authenticated": "Not authenticated",
            "registration_closed": "Public registration is closed",
            "token_not_found": "Token not found",
            "email_registered": "Email is already registered: ${email}",
            "email_in_use": "Email is already in use: ${email}",
            "avatar_not_found": "Avatar not found",
            "invalid_avatar_type": "Unsupported avatar type. Allowed types: ${types}",
            "invalid_avatar_content": "The selected file is not a valid supported image",
            "avatar_too_large": "The avatar must not exceed 5 MB",
        },
    },
}
