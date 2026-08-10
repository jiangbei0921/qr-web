"""qrkit — 新一代二维码生成内核（分层、可插件扩展）。"""
from .types import registry, QRTypeBuilder, QRTypeRegistry, QRValidationError
from .render import render_png, render_svg

__all__ = [
    'registry',
    'QRTypeBuilder',
    'QRTypeRegistry',
    'QRValidationError',
    'render_png',
    'render_svg',
]
