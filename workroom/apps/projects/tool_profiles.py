"""Presentation/configuration templates, independent of authorization."""
PROFILES = {
    'codex':'Codex', 'workbuddy':'WorkBuddy', 'cursor':'Cursor',
    'harness':'DeepSeek Harness', 'claude-code':'Claude Code', 'custom':'自定义 MCP 客户端',
}
CAPABILITIES = [('code_read','阅读代码'),('code_write','修改代码'),('tests','运行检查'),
                ('browser','浏览器验证'),('documents','文档处理')]
