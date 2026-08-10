"""二维码类型系统：每个类型自带字段定义、校验与规范编码，注册表驱动扩展。

设计要点：
- 旧实现把 url/text/email/vcard/wifi 全部硬编码在 shared.format_qrcode_payload 的 if 链里，
  且 WiFi/vCard 编码未对 ; , 反斜杠 : " 等字符转义（规范强制），含这些字符会扫不出。
- 新架构：每个类型是一个 QRTypeBuilder 子类，自带 validate（校验+清洗）与 build_payload（含转义），
  新增类型 = 注册一个类，核心零改动。
"""
import re
from urllib.parse import quote


class QRValidationError(ValueError):
    """类型字段校验失败，在 API 层映射为 HTTP 400。"""


# ---------- 规范转义工具（致命 bug 修复点） ----------
def escape_wifi(value):
    """WiFi/MECARD 规范转义：\\ ; , " : 必须反斜杠转义。

    旧实现直接 f-string 拼接，含这些字符的 WiFi 码无法被扫码识别。
    """
    if value is None:
        return ''
    return (str(value)
            .replace('\\', '\\\\')
            .replace(';', '\\;')
            .replace(',', '\\,')
            .replace('"', '\\"')
            .replace(':', '\\:'))


def escape_vcard(value):
    """vCard 文本字段转义：反斜杠、逗号、分号、换行。"""
    if value is None:
        return ''
    return (str(value)
            .replace('\\', '\\\\')
            .replace(',', '\\,')
            .replace(';', '\\;')
            .replace('\n', '\\n')
            .replace('\r', ''))


# ---------- 类型基类 ----------
class QRTypeBuilder:
    """二维码类型基类。子类定义 type_key、label、fields，并实现 build_payload。

    fields 为前端自描述表单提供 schema：
        {key, label, required, placeholder?, default?, options?}
    """
    type_key = ''
    label = ''
    fields = []

    def validate(self, fields):
        """校验并清洗字段，失败抛 QRValidationError。"""
        fields = fields or {}
        cleaned = {}
        for f in self.fields:
            key = f['key']
            val = fields.get(key)
            if f.get('required') and not str(val or '').strip():
                raise QRValidationError(f"字段「{f['label']}」为必填项")
            cleaned[key] = val
        return cleaned

    def build_payload(self, fields):
        """将字段编码为二维码内容字符串（含规范转义）。子类必须实现。"""
        raise NotImplementedError


# ---------- 内置类型 ----------
class UrlType(QRTypeBuilder):
    type_key = 'url'
    label = '网址'
    fields = [{'key': 'url', 'label': '网址', 'required': True, 'placeholder': 'example.com'}]

    def build_payload(self, f):
        u = (f.get('url') or '').strip()
        if not u:
            raise QRValidationError('网址不能为空')
        # 容错：缺 scheme 自动补 https（符合用户"随手出码"习惯）
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', u) and not u.startswith('//'):
            u = 'https://' + u
        return u


class TextType(QRTypeBuilder):
    type_key = 'text'
    label = '文本'
    fields = [{'key': 'text', 'label': '文本', 'required': True, 'placeholder': '输入任意文本'}]

    def build_payload(self, f):
        t = f.get('text') or ''
        if not t.strip():
            raise QRValidationError('文本内容不能为空')
        return t


class EmailType(QRTypeBuilder):
    type_key = 'email'
    label = '邮件'
    fields = [
        {'key': 'email', 'label': '收件人', 'required': True},
        {'key': 'subject', 'label': '主题', 'required': False},
        {'key': 'body', 'label': '正文', 'required': False},
    ]
    _EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

    def build_payload(self, f):
        email = (f.get('email') or '').strip()
        if not email:
            raise QRValidationError('收件人邮箱不能为空')
        if not self._EMAIL_RE.match(email):
            raise QRValidationError('邮箱格式不正确')
        subject = quote(f.get('subject') or '')
        body = quote(f.get('body') or '')
        extra = f'subject={subject}&body={body}' if (subject or body) else ''
        return f'mailto:{email}' + (f'?{extra}' if extra else '')


class VCardType(QRTypeBuilder):
    type_key = 'vcard'
    label = '联系人名片'
    fields = [
        {'key': 'name', 'label': '姓名', 'required': True},
        {'key': 'phone', 'label': '电话', 'required': False},
        {'key': 'email', 'label': '邮箱', 'required': False},
        {'key': 'company', 'label': '公司', 'required': False},
        {'key': 'title', 'label': '职位', 'required': False},
    ]

    def build_payload(self, f):
        name = escape_vcard(f.get('name') or '')
        if not name.strip():
            raise QRValidationError('姓名不能为空')
        lines = ['BEGIN:VCARD', 'VERSION:3.0', f'N:{name}', f'FN:{name}']
        if f.get('company'):
            lines.append(f"ORG:{escape_vcard(f['company'])}")
        if f.get('title'):
            lines.append(f"TITLE:{escape_vcard(f['title'])}")
        if f.get('phone'):
            lines.append(f"TEL:{escape_vcard(f['phone'])}")
        if f.get('email'):
            lines.append(f"EMAIL:{escape_vcard(f['email'])}")
        lines.append('END:VCARD')
        return '\n'.join(lines)


class WifiType(QRTypeBuilder):
    type_key = 'wifi'
    label = 'WiFi'
    fields = [
        {'key': 'ssid', 'label': '网络名称(SSID)', 'required': True},
        {'key': 'password', 'label': '密码', 'required': False},
        {'key': 'security', 'label': '加密方式', 'required': False, 'default': 'WPA',
         'options': ['WPA', 'WEP', 'nopass']},
    ]

    def build_payload(self, f):
        ssid = escape_wifi(f.get('ssid') or '')
        if not ssid.strip():
            raise QRValidationError('SSID 不能为空')
        security = str(f.get('security') or 'WPA').strip().upper()
        if security not in ('WPA', 'WEP', 'NOPASS'):
            security = 'WPA'
        parts = [f'T:{security}', f'S:{ssid}']
        if security != 'NOPASS':
            parts.append(f"P:{escape_wifi(f.get('password') or '')}")
        parts.append('H:false')
        return 'WIFI:' + ';'.join(parts) + ';;'


# ---------- 注册表 ----------
class QRTypeRegistry:
    """类型注册表：新增类型只需 register 一个子类，核心逻辑零改动。"""

    def __init__(self):
        self._types = {}

    def register(self, builder_cls):
        inst = builder_cls()
        self._types[inst.type_key] = inst
        return builder_cls

    def get(self, key):
        return self._types.get(key)

    def all(self):
        return list(self._types.values())

    def describe(self):
        """返回供前端动态生成表单的自描述 schema。"""
        return [
            {'type': t.type_key, 'label': t.label, 'fields': t.fields}
            for t in self._types.values()
        ]


registry = QRTypeRegistry()
for _cls in (UrlType, TextType, EmailType, VCardType, WifiType):
    registry.register(_cls)
