"""TUI 脚手架测试：依赖可用、模块可导入。"""

def test_textual依赖可用():
    """验证 textual 库已安装。"""
    import textual
    assert textual.__version__ >= "0.50"

def test_tui模块可导入():
    """验证 app.tui 模块存在。"""
    from app.tui import __version__
    assert __version__ == "0.1.0"
