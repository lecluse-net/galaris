"""Chinese approval previews."""

default: dict[str, object] = {
    "approval_preview": {
        "send_mail": "发送电子邮件", "run_function": "使用功能 ${function}",
        "to": "收件人", "cc": "抄送", "bcc": "密送", "subject": "主题", "body": "正文",
        "html_body": "HTML 版本（源文本）", "reply_to": "回复地址", "attachments": "附件",
        "command": "命令", "cwd": "工作目录", "path": "路径", "url": "网址", "content": "内容",
        "destination": "目标", "source": "来源", "yes": "是", "no": "否",
        "truncated": "预览已缩短。请在权限页面打开此请求，查看完整内容后再做决定。",
    },
}
