"""Chinese approval previews."""

default: dict[str, object] = {
    "tools": {
        "errors": {
            "invalid_resource_tool_code": (
                "启用文件共享或消息功能的工具技术名称必须以小写字母开头，且只能包含小写字母、"
                "数字及 +、.、-。请将下划线和空格替换为连字符（例如 team-share）。"
            ),
        },
    },
    "approval_preview": {
        "send_mail": "发送电子邮件", "run_function": "使用功能 ${function}",
        "process_mail": "允许读取和处理此电子邮件", "sender": "发件人",
        "to": "收件人", "cc": "抄送", "bcc": "密送", "subject": "主题", "body": "正文",
        "html_body": "HTML 版本（源文本）", "reply_to": "回复地址", "attachments": "附件",
        "command": "命令", "cwd": "工作目录", "path": "路径", "url": "网址", "content": "内容",
        "destination": "目标", "source": "来源", "yes": "是", "no": "否",
        "truncated": "预览已缩短。请在权限页面打开此请求，查看完整内容后再做决定。",
    },
}
