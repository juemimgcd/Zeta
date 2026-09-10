"""Zeta package."""

from importlib.metadata import version

# 从已安装的 zeta 包元数据读取版本字符串，用于 CLI --version。
__version__ = version("zeta")
