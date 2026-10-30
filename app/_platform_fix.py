"""平台查询加固：Windows 下短路 platform 的 WMI 查询。

本机 WMI 服务异常时，platform.uname()/machine()/win32_ver() 会阻塞数百秒。
aiohttp（openai 依赖）、pymilvus → pandas 等第三方库在导入阶段就会调用它们，
导致 API / Celery 进程启动阶段卡死。

这里替换为静态值，只影响版本号等展示信息，不影响系统真正的平台判定。
进程启动时由项目根 sitecustomize.py 提前加载，app 内模块也会显式导入兜底。
"""
from __future__ import annotations

import platform
import sys
from collections import namedtuple

if sys.platform == "win32":
    _Uname = namedtuple("uname_result", "system node release version machine processor")
    _STATIC_UNAME = _Uname("Windows", "localhost", "10", "10.0.19045", "AMD64", "Intel64 Family 6")
    platform.uname = lambda *args, **kwargs: _STATIC_UNAME  # type: ignore[assignment]
    platform.system = lambda *args, **kwargs: "Windows"  # type: ignore[assignment]
    platform.machine = lambda *args, **kwargs: "AMD64"  # type: ignore[assignment]
    platform.win32_ver = lambda *args, **kwargs: ("10", "10.0.19045", "SP0", "Multiprocessor Free")  # type: ignore[assignment]
