"""二维码类型系统：每个类型自带字段定义、校验与规范编码，注册表驱动扩展。

设计要点：
- 旧实现把 url/text/email/vcard/wifi 全部硬编码在 shared.format_qrcode_payload 的 if 链里，
  且 WiFi/vCard 编码未对 ; , 反斜杠 : " 等字符转义（规范强制），含这些字符会扫不出。
- 新架构：每个类型是一个 QRTypeBuilder 子类，自带 validate（校验+清洗）与 build_payload（含转义），
  新增类型 = 注册一个类，核心零改动。
"""
import datetime
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


def escape_ical(value):
    """iCalendar(RFC 5545) 文本转义：反斜杠、逗号、分号、换行。"""
    if value is None:
        return ''
    return (str(value)
            .replace('\\', '\\\\')
            .replace(',', '\\,')
            .replace(';', '\\;')
            .replace('\r\n', '\\n')
            .replace('\n', '\\n')
            .replace('\r', '\\n'))


def _as_bool(v):
    """把前端可能传来的字符串/布尔统一成 bool。"""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'on')


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
        {'key': 'hidden', 'label': '隐藏网络(不广播 SSID)', 'type': 'bool', 'default': False},
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
        parts.append(f'H:{str(_as_bool(f.get('hidden'))).lower()}')
        return 'WIFI:' + ';'.join(parts) + ';;'


class SmsType(QRTypeBuilder):
    type_key = 'sms'
    label = '短信'
    fields = [
        {'key': 'phone', 'label': '手机号码', 'required': True, 'placeholder': '13800138000'},
        {'key': 'body', 'label': '短信内容', 'required': False},
    ]

    def build_payload(self, f):
        phone = (f.get('phone') or '').strip()
        if not phone:
            raise QRValidationError('手机号码不能为空')
        body = f.get('body') or ''
        return f'SMSTO:{phone}:{body}'


class TelType(QRTypeBuilder):
    type_key = 'tel'
    label = '电话'
    fields = [
        {'key': 'phone', 'label': '电话号码', 'required': True, 'placeholder': '13800138000'},
    ]

    def build_payload(self, f):
        phone = (f.get('phone') or '').strip()
        if not phone:
            raise QRValidationError('电话号码不能为空')
        return f'tel:{phone}'


class GeoType(QRTypeBuilder):
    type_key = 'geo'
    label = '地理位置'
    fields = [
        {'key': 'lat', 'label': '纬度 (lat)', 'required': True, 'placeholder': '39.9042'},
        {'key': 'lng', 'label': '经度 (lng)', 'required': True, 'placeholder': '116.4074'},
    ]

    def build_payload(self, f):
        lat = (f.get('lat') or '').strip()
        lng = (f.get('lng') or '').strip()
        try:
            float(lat)
            float(lng)
        except (TypeError, ValueError):
            raise QRValidationError('经纬度必须是数字')
        if not lat or not lng:
            raise QRValidationError('经纬度不能为空')
        return f'geo:{lat},{lng}'


class EventType(QRTypeBuilder):
    type_key = 'event'
    label = '日历事件'
    fields = [
        {'key': 'summary', 'label': '事件标题', 'required': True, 'placeholder': '团队周会'},
        {'key': 'start', 'label': '开始时间', 'required': True, 'placeholder': '2026-09-01 14:30'},
        {'key': 'end', 'label': '结束时间', 'required': False, 'placeholder': '2026-09-01 15:30'},
        {'key': 'location', 'label': '地点', 'required': False},
        {'key': 'description', 'label': '描述', 'required': False},
    ]
    _DT_FORMATS = (
        '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M', '%Y-%m-%d',
    )

    @classmethod
    def _parse_dt(cls, raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        for fmt in cls._DT_FORMATS:
            try:
                return datetime.datetime.strptime(raw, fmt)
            except ValueError:
                continue
        raise QRValidationError('时间格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM')

    @classmethod
    def _ical_dt(cls, dt):
        if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
            return dt.strftime('%Y%m%d')
        return dt.strftime('%Y%m%dT%H%M%S')

    def build_payload(self, f):
        summary = (f.get('summary') or '').strip()
        if not summary:
            raise QRValidationError('事件标题不能为空')
        start = self._parse_dt(f.get('start'))
        if start is None:
            raise QRValidationError('开始时间不能为空')
        end = self._parse_dt(f.get('end')) if f.get('end') else None
        if end is not None and end < start:
            raise QRValidationError('结束时间不能早于开始时间')
        now = datetime.datetime.now()
        uid = f'zhiqr-{now.strftime("%Y%m%d%H%M%S")}-{abs(hash(summary)) % 100000}@zhiqr'
        lines = [
            'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ZhiQR//ZH',
            'CALSCALE:GREGORIAN', 'BEGIN:VEVENT',
            f'UID:{uid}', f'DTSTAMP:{self._ical_dt(now)}',
            f'DTSTART:{self._ical_dt(start)}',
        ]
        if end is not None:
            lines.append(f'DTEND:{self._ical_dt(end)}')
        lines.append(f'SUMMARY:{escape_ical(summary)}')
        if f.get('location'):
            lines.append(f"LOCATION:{escape_ical(f['location'])}")
        if f.get('description'):
            lines.append(f"DESCRIPTION:{escape_ical(f['description'])}")
        lines += ['END:VEVENT', 'END:VCALENDAR']
        return '\r\n'.join(lines)


class AppType(QRTypeBuilder):
    type_key = 'app'
    label = '应用下载'
    fields = [
        {'key': 'platform', 'label': '平台', 'required': True, 'default': 'ios',
         'options': ['ios', 'android', 'url']},
        {'key': 'identifier', 'label': 'App ID / 包名 / 链接', 'required': True,
         'placeholder': 'ios 填 id、android 填包名、url 填直链'},
    ]
    _URL_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://')

    def build_payload(self, f):
        platform = str(f.get('platform') or 'ios').strip().lower()
        ident = (f.get('identifier') or '').strip()
        if not ident:
            raise QRValidationError('标识符不能为空')
        if platform == 'ios':
            if not ident.isdigit():
                raise QRValidationError('iOS 应填写纯数字 App ID')
            return f'https://apps.apple.com/app/id{ident}'
        if platform == 'android':
            if not re.match(r'^[a-zA-Z0-9_.\-]+$', ident):
                raise QRValidationError('Android 应填写合法包名(如 com.xxx.app)')
            return f'https://play.google.com/store/apps/details?id={ident}'
        # url：直链，容错补 scheme
        if not self._URL_RE.match(ident) and not ident.startswith('//'):
            ident = 'https://' + ident
        return ident


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
for _cls in (UrlType, TextType, EmailType, VCardType, WifiType, SmsType, TelType, GeoType, EventType, AppType):
    registry.register(_cls)
