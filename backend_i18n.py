"""
后端国际化模块
支持从请求中检测用户语言偏好，返回对应语言的翻译文本
使用与前端相同的 JSON 语言包文件
"""
import json
import os
from flask import request, session

# 语言包目录
LANG_DIR = os.path.join(os.path.dirname(__file__), 'static', 'lang')

# 支持的语言及对应的 Accept-Language 前缀
SUPPORTED_LOCALES = {
    'zh': ['zh'],
    'en': ['en'],
    'ja': ['ja'],
    'ko': ['ko'],
}

# 语言包缓存
_translations_cache = {}

# 默认回退语言
FALLBACK_LOCALE = 'zh'


def _normalize_locale(locale):
    """规范化语言代码，兼容 zh-CN / en-US 等格式"""
    if not locale:
        return None
    code = str(locale).strip().lower()
    if not code:
        return None
    code = code.split('-')[0]
    return code if code in SUPPORTED_LOCALES else None


def _load_locale(locale):
    """加载指定语言的语言包"""
    if locale in _translations_cache:
        return _translations_cache[locale]
    filepath = os.path.join(LANG_DIR, f'{locale}.json')
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _translations_cache[locale] = data
        return data
    except (json.JSONDecodeError, IOError):
        return {}


def _get_nested_value(obj, path):
    """从嵌套对象中获取值，支持 a.b.c 格式"""
    if not obj or not path:
        return None
    keys = path.split('.')
    current = obj
    for k in keys:
        if current is None or not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


def _interpolate(template, params):
    """插值替换 {{variable}}"""
    if not isinstance(template, str):
        return template
    import re
    def replacer(match):
        key = match.group(1)
        return str(params.get(key, match.group(0)))
    return re.sub(r'\{\{(\w+)\}\}', replacer, template)


def get_locale():
    """
    从请求中检测用户语言偏好
    优先级：1. URL 参数 ?lang=  2. session  3. Accept-Language 头
    """
    # 1. URL 参数
    lang_param = _normalize_locale(request.args.get('lang'))
    if lang_param:
        return lang_param

    # 2. Session（优先 preferred_lang，其次 lang）
    for key in ('preferred_lang', 'lang'):
        session_lang = _normalize_locale(session.get(key))
        if session_lang:
            return session_lang

    # 3. Accept-Language 头
    accept_lang = request.headers.get('Accept-Language', '')
    if accept_lang:
        for part in accept_lang.split(','):
            lang_code = part.split(';')[0].strip().lower()
            for locale, prefixes in SUPPORTED_LOCALES.items():
                for prefix in prefixes:
                    if lang_code.startswith(prefix):
                        return locale

    return FALLBACK_LOCALE


def t(key, params=None, locale=None):
    """
    翻译指定 key
    :param key: 翻译键，如 'auth.loginFailed'
    :param params: 插值参数字典
    :param locale: 指定语言，为 None 时自动检测
    :return: 翻译后的文本
    """
    if locale is None:
        locale = get_locale()

    translations = _load_locale(locale)
    value = _get_nested_value(translations, key)

    # 回退到默认语言
    if value is None and locale != FALLBACK_LOCALE:
        fallback = _load_locale(FALLBACK_LOCALE)
        value = _get_nested_value(fallback, key)

    if value is None:
        return key

    if params:
        return _interpolate(value, params)
    return value


def t_or(key, default, params=None, locale=None):
    """
    翻译 key，如果不存在则返回默认值
    用于兼容旧的硬编码字符串
    """
    result = t(key, params, locale)
    if result == key:
        return default
    return result


def clear_cache():
    """清除语言包缓存（用于开发环境热更新）"""
    _translations_cache.clear()