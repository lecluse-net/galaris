"""Chinese browser permission messages."""

default: dict[str, object] = {
    "browser": {
        "permission_question": "允许此代理的浏览器对 ${origin} 执行 ${action} 访问吗？此决定涵盖该来源的所有路径，并将为此代理保存。",
        "all_sites_permission_question": "始终允许此代理的浏览器访问所有网站，不再请求网站授权吗？此授权涵盖所有域名、协议、端口、路径、已配置的 HTTP 方法和 WebSocket。网络过滤器、明确拒绝和单独的本地网络权限仍然有效。您可以在已记住的权限中撤销此授权。",
        "errors": {
            "invalid_url": "URL 无效。请使用不包含登录凭据的 HTTP(S) URL。",
            "invalid_viewport": "视口宽度必须为 320–3840 CSS 像素，高度必须为 240–2160 CSS 像素。",
            "session_not_found": "此浏览器会话不可用或已不属于此任务。",
            "capacity_reached": "浏览器已达容量上限。请关闭现有会话或稍后重试。",
            "unavailable": "隔离浏览器服务不可用。",
            "failed": "浏览器操作失败（${code}）。",
        },
        "closed": "浏览器会话 ${session_id} 已关闭。",
    },
}
