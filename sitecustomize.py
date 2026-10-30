"""Python 启动最早期加载的平台查询加固（见 app/_platform_fix.py）。

本机 WMI 服务异常时 platform 查询会阻塞数百秒，pymilvus/pandas/aiohttp 导入即卡死。
放在项目根，Python 启动时会自动导入本模块（需项目根在 sys.path，启动脚本已设 PYTHONPATH）。
"""
try:
    import app._platform_fix  # noqa: F401
except Exception:
    pass
