/**
 * 智码云 - 二维码多终端预览中心
 * 设备配置声明文件
 * 新增设备仅需在此添加配置项，无需修改任何渲染逻辑
 */
const DEVICE_CONFIG = {
    'iphone': {
        name: 'iPhone 15 Pro',
        icon: '📱',
        category: 'phone',
        shell: {
            type: 'phone',
            width: 393,
            height: 852,
            screenX: 16,
            screenY: 56,
            screenWidth: 361,
            screenHeight: 740,
            borderRadius: 44,
            notch: true,
            notchWidth: 126,
            notchHeight: 32,
            homeIndicator: true
        },
        defaultOrientation: 'portrait',
        zoom: { min: 0.3, max: 1.5, default: 0.8 }
    },
    'android': {
        name: 'Android (Pixel 8)',
        icon: '🤖',
        category: 'phone',
        shell: {
            type: 'phone',
            width: 412,
            height: 915,
            screenX: 16,
            screenY: 48,
            screenWidth: 380,
            screenHeight: 819,
            borderRadius: 36,
            notch: false,
            punchHole: true,
            punchHoleSize: 12,
            homeIndicator: true
        },
        defaultOrientation: 'portrait',
        zoom: { min: 0.3, max: 1.5, default: 0.8 }
    },
    'ipad': {
        name: 'iPad Pro 12.9"',
        icon: '📋',
        category: 'tablet',
        shell: {
            type: 'tablet',
            width: 1024,
            height: 1366,
            screenX: 32,
            screenY: 40,
            screenWidth: 960,
            screenHeight: 1286,
            borderRadius: 24,
            notch: false,
            homeIndicator: true
        },
        defaultOrientation: 'portrait',
        zoom: { min: 0.2, max: 1.0, default: 0.5 }
    },
    'pc': {
        name: 'PC (1920×1080)',
        icon: '🖥',
        category: 'desktop',
        shell: {
            type: 'desktop',
            width: 1440,
            height: 900,
            screenX: 0,
            screenY: 40,
            screenWidth: 1440,
            screenHeight: 860,
            borderRadius: 0,
            browserFrame: true,
            browserBar: 40,
            scrollbar: 12
        },
        defaultOrientation: 'landscape',
        zoom: { min: 0.2, max: 1.0, default: 0.4 }
    },
    'mac': {
        name: 'MacBook Pro 16"',
        icon: '🍎',
        category: 'desktop',
        shell: {
            type: 'desktop',
            width: 1440,
            height: 900,
            screenX: 0,
            screenY: 40,
            screenWidth: 1440,
            screenHeight: 860,
            borderRadius: 0,
            browserFrame: true,
            browserBar: 40,
            scrollbar: 12
        },
        defaultOrientation: 'landscape',
        zoom: { min: 0.2, max: 1.0, default: 0.4 }
    },
    'wechat': {
        name: '微信内置浏览器',
        icon: '💬',
        category: 'inapp',
        shell: {
            type: 'inapp',
            width: 393,
            height: 852,
            screenX: 0,
            screenY: 88,
            screenWidth: 393,
            screenHeight: 684,
            borderRadius: 0,
            wechatTopBar: true,
            wechatBottomBar: true,
            topBarHeight: 88,
            bottomBarHeight: 80
        },
        defaultOrientation: 'portrait',
        zoom: { min: 0.3, max: 1.5, default: 0.8 }
    }
};

const ZOOM_LEVELS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5];
const THEME_OPTIONS = [
    { key: 'light',  label: '亮色', icon: '☀️' },
    { key: 'dark',   label: '暗黑', icon: '🌙' },
    { key: 'auto',   label: '自动', icon: '🔄' }
];