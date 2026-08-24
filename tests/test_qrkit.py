"""qrkit 内核单元测试（stdlib unittest，无需 Flask / 外部服务）。

覆盖：
- 各类型 builder 的规范编码与转义（WiFi / vCard / iCal / mailto）
- 字段校验（必填、格式、范围）
- _clean_options 参数校验与兜底
- render 三格式（PNG / SVG / PDF）产出与 logo / 透明背景

运行：在 qr-analysis 目录执行  python -m unittest tests.test_qrkit -v
"""
import base64
import io
import os
import sys
import unittest

# 确保能从仓库根导入 routes 包
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from routes.qrkit import types as T
from routes.qrkit import render as R
from routes.qrkit.api import _clean_options


class TestEscapers(unittest.TestCase):
    def test_escape_wifi(self):
        self.assertEqual(T.escape_wifi('a;b,c:d"e\\f'),
                         'a\\;b\\,c\\:d\\"e\\\\f')

    def test_escape_vcard(self):
        self.assertEqual(T.escape_vcard('a,b;c\nd'),
                         'a\\,b\\;c\\nd')

    def test_escape_ical(self):
        self.assertEqual(T.escape_ical('a,b;c\nd'),
                         'a\\,b\\;c\\nd')


class TestBuilders(unittest.TestCase):
    def test_wifi_escaping_and_hidden(self):
        b = T.registry.get('wifi')
        p = b.build_payload(b.validate({'ssid': 'My;Net', 'password': 'p@ss,w0rd', 'security': 'WPA'}))
        self.assertIn('S:My\\;Net', p)
        self.assertIn('P:p@ss\\,w0rd', p)
        self.assertIn('H:false', p)
        ph = b.build_payload(b.validate({'ssid': 'X', 'hidden': True}))
        self.assertIn('H:true', ph)
        pstr = b.build_payload(b.validate({'ssid': 'X', 'hidden': 'yes'}))
        self.assertIn('H:true', pstr)

    def test_wifi_nopass_no_password(self):
        b = T.registry.get('wifi')
        p = b.build_payload(b.validate({'ssid': 'Open', 'security': 'nopass'}))
        self.assertNotIn('P:', p)
        self.assertIn('T:NOPASS', p)

    def test_wifi_missing_ssid(self):
        b = T.registry.get('wifi')
        with self.assertRaises(T.QRValidationError):
            b.build_payload(b.validate({'ssid': ''}))

    def test_vcard_escape(self):
        b = T.registry.get('vcard')
        p = b.build_payload(b.validate({'name': '张,三', 'company': 'A;B'}))
        self.assertIn('N:张\\,三', p)
        self.assertIn('ORG:A\\;B', p)
        self.assertIn('BEGIN:VCARD', p)
        self.assertIn('END:VCARD', p)

    def test_email_mailto_and_encoding(self):
        b = T.registry.get('email')
        p = b.build_payload(b.validate({'email': 'a@b.com', 'subject': 'hi there', 'body': 'line1'}))
        self.assertTrue(p.startswith('mailto:a@b.com?'))
        self.assertIn('subject=hi%20there', p)
        with self.assertRaises(T.QRValidationError):
            b.build_payload(b.validate({'email': 'not-an-email'}))

    def test_sms_tel_geo(self):
        sms = T.registry.get('sms').build_payload(T.registry.get('sms').validate({'phone': '138', 'body': 'hi'}))
        self.assertEqual(sms, 'SMSTO:138:hi')
        tel = T.registry.get('tel').build_payload(T.registry.get('tel').validate({'phone': '138'}))
        self.assertEqual(tel, 'tel:138')
        with self.assertRaises(T.QRValidationError):
            T.registry.get('geo').build_payload({'lat': 'abc', 'lng': '1'})
        geo = T.registry.get('geo').build_payload({'lat': '39.9', 'lng': '116.4'})
        self.assertEqual(geo, 'geo:39.9,116.4')

    def test_event_vevent(self):
        b = T.registry.get('event')
        p = b.build_payload(b.validate({'summary': '会议', 'start': '2026-09-01 14:30',
                                        'end': '2026-09-01 15:30', 'location': 'A;B 厅'}))
        self.assertIn('BEGIN:VCALENDAR', p)
        self.assertIn('BEGIN:VEVENT', p)
        self.assertIn('SUMMARY:会议', p)
        self.assertIn('DTSTART:20260901T143000', p)
        self.assertIn('DTEND:20260901T153000', p)
        self.assertIn('LOCATION:A\\;B 厅', p)
        # 结束早于开始应报错
        with self.assertRaises(T.QRValidationError):
            b.build_payload(b.validate({'summary': 'x', 'start': '2026-09-01 15:30', 'end': '2026-09-01 14:30'}))
        # 非法时间
        with self.assertRaises(T.QRValidationError):
            b.build_payload(b.validate({'summary': 'x', 'start': 'not-a-date'}))

    def test_app_links(self):
        b = T.registry.get('app')
        self.assertEqual(b.build_payload(b.validate({'platform': 'ios', 'identifier': '123456789'})),
                         'https://apps.apple.com/app/id123456789')
        self.assertEqual(b.build_payload(b.validate({'platform': 'android', 'identifier': 'com.x.app'})),
                         'https://play.google.com/store/apps/details?id=com.x.app')
        self.assertEqual(b.build_payload(b.validate({'platform': 'url', 'identifier': 'example.com/x'})),
                         'https://example.com/x')
        with self.assertRaises(T.QRValidationError):
            b.build_payload(b.validate({'platform': 'ios', 'identifier': 'abc'}))  # 非数字
        with self.assertRaises(T.QRValidationError):
            b.build_payload(b.validate({'platform': 'android', 'identifier': 'bad pkg'}))

    def test_registry_describe_includes_new_types(self):
        keys = [t['type'] for t in T.registry.describe()]
        for k in ('wifi', 'event', 'app'):
            self.assertIn(k, keys)


class TestCleanOptions(unittest.TestCase):
    def test_defaults(self):
        o = _clean_options({})
        self.assertEqual(o['error_correction'], 'M')
        self.assertEqual(o['fill_color'], '#000000')
        self.assertEqual(o['back_color'], '#FFFFFF')
        self.assertFalse(o.get('transparent_bg'))

    def test_bad_ec_falls_back(self):
        self.assertEqual(_clean_options({'error_correction': 'Z'})['error_correction'], 'M')

    def test_bad_color_falls_back(self):
        self.assertEqual(_clean_options({'fill_color': 'red'})['fill_color'], '#000000')

    def test_size_clamped(self):
        self.assertEqual(_clean_options({'size': 10})['size'], 0)   # 低于下限 64
        self.assertEqual(_clean_options({'size': 4096})['size'], 4096)
        self.assertEqual(_clean_options({'size': 99999})['size'], 0)

    def test_logo_and_transparent(self):
        o = _clean_options({'logo': 'data:image/png;base64,AAAA', 'transparent_bg': True})
        self.assertEqual(o['logo'], 'data:image/png;base64,AAAA')
        self.assertTrue(o['transparent_bg'])


class TestRender(unittest.TestCase):
    def _opts(self, **kw):
        base = {'error_correction': 'M', 'fill_color': '#000000', 'back_color': '#FFFFFF',
                'style': 'square', 'size': 300}
        base.update(kw)
        return base

    def test_png_header(self):
        b = R.render_png('https://example.com', self._opts())
        self.assertTrue(b.startswith(b'\x89PNG'))

    def test_svg_contains_svg(self):
        s = R.render_svg('https://example.com', self._opts())
        self.assertIn('<svg', s)

    def test_pdf_header(self):
        b = R.render_pdf('https://example.com', self._opts())
        self.assertTrue(b.startswith(b'%PDF'))

    def test_transparent_bg_rgba(self):
        from PIL import Image
        b = R.render_png('https://example.com', self._opts(transparent_bg=True))
        img = Image.open(io.BytesIO(b))
        self.assertEqual(img.mode, 'RGBA')

    def test_logo_overlay(self):
        from PIL import Image
        # 造一个 64x64 红色方块 data URI
        buf = io.BytesIO()
        Image.new('RGBA', (64, 64), (255, 0, 0, 255)).save(buf, 'PNG')
        uri = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
        b = R.render_png('https://example.com', self._opts(logo=uri))
        self.assertTrue(b.startswith(b'\x89PNG'))
        img = Image.open(io.BytesIO(b))
        self.assertEqual(img.mode, 'RGBA')


if __name__ == '__main__':
    unittest.main(verbosity=2)
