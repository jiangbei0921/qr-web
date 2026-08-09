/**
 * 智码云 - 二维码生成器
 * 前端交互脚本
 */

// ============================================================
// I18n 国际化系统
// 设计理念参考 i18next：语言包分离、命名空间、插值、回退语言
// ============================================================
class I18n {
    constructor(options = {}) {
        this.locales = options.locales || {
            'zh': '/static/lang/zh.json',
            'en': '/static/lang/en.json',
            'ja': '/static/lang/ja.json',
            'ko': '/static/lang/ko.json'
        };
        this.fallbackLocale = options.fallbackLocale || 'zh';
        this._cache = {};          // 已加载的语言包缓存
        this._currentLocale = null;
        this._translations = {};   // 当前语言包的翻译数据
        this._loaded = false;
        this._loading = false;
        this._loadPromise = null;
        this._changeCallbacks = []; // 语言切换后的回调列表
    }

    // 初始化：从 localStorage 读取语言偏好，加载语言包并应用到 DOM
    async init() {
        const saved = this._normalizeLocale(window.__INITIAL_LOCALE__ || localStorage.getItem('lang') || this._detectBrowserLang() || this.fallbackLocale);
        await this.setLocale(saved);
        return this;
    }

    // 检测浏览器语言偏好
    _detectBrowserLang() {
        const lang = (navigator.language || navigator.userLanguage || '').toLowerCase();
        if (lang.startsWith('zh')) return 'zh';
        if (lang.startsWith('ja')) return 'ja';
        if (lang.startsWith('ko')) return 'ko';
        if (lang.startsWith('en')) return 'en';
        return null;
    }

    // 获取当前语言
    get currentLocale() {
        return this._currentLocale || this.fallbackLocale;
    }

    _normalizeLocale(locale) {
        if (!locale) return this.fallbackLocale;
        const code = String(locale).trim().toLowerCase();
        if (code.startsWith('zh')) return 'zh';
        if (code.startsWith('ja')) return 'ja';
        if (code.startsWith('ko')) return 'ko';
        if (code.startsWith('en')) return 'en';
        return this.fallbackLocale;
    }

    // 设置语言
    async setLocale(locale) {
        locale = this._normalizeLocale(locale);
        if (!this.locales[locale]) {
            console.warn('[I18n] Unsupported locale:', locale, ', falling back to', this.fallbackLocale);
            locale = this.fallbackLocale;
        }
        if (this._currentLocale === locale && this._loaded) return;

        this._currentLocale = locale;
        this._loaded = false;

        // 优先从缓存获取
        if (this._cache[locale]) {
            this._translations = this._cache[locale];
            this._loaded = true;
        } else {
            if (!this._loading) {
                this._loadPromise = this._fetchLocale(locale);
            }
            await this._loadPromise;
        }

        localStorage.setItem('lang', locale);
        document.documentElement.lang = this._htmlLang(locale);
        const meta = (this._translations && this._translations.meta) || {};
        document.documentElement.dir = meta.dir || 'ltr';
        document.documentElement.setAttribute('data-locale', locale);
        this._applyToDOM();
        this._syncLocaleToServer(locale);
        this._updateLangToggle();
        this._fireChangeCallbacks();
    }

    // 获取 HTML lang 属性值
    _htmlLang(locale) {
        const map = { 'zh': 'zh-CN', 'en': 'en', 'ja': 'ja', 'ko': 'ko' };
        return map[locale] || locale;
    }

    // 懒加载语言包
    async _fetchLocale(locale) {
        this._loading = true;
        try {
            const url = this.locales[locale];
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            this._cache[locale] = data;
            this._translations = data;
            this._loaded = true;
        } catch (e) {
            console.error('[I18n] Failed to load locale:', locale, e);
            // 回退处理
            if (locale !== this.fallbackLocale) {
                console.warn('[I18n] Falling back to', this.fallbackLocale);
                return this.setLocale(this.fallbackLocale);
            }
            this._translations = {};
            this._loaded = true;
        } finally {
            this._loading = false;
        }
    }

    // 核心翻译函数：支持点号分隔的 key 和插值
    // 用法: i18n.t('nav.workspace') 或 i18n.t('common.total', {count: 5})
    t(key, params = {}) {
        if (!key) return '';
        let value = this._getNestedValue(this._translations, key);
        if (value === undefined) {
            // 回退到 fallback 语言
            if (this._currentLocale !== this.fallbackLocale && this._cache[this.fallbackLocale]) {
                value = this._getNestedValue(this._cache[this.fallbackLocale], key);
            }
        }
        if (value === undefined) {
            // 仍找不到，返回 key 本身作为开发提示
            console.warn('[I18n] Missing translation for key:', key);
            return key;
        }
        return this._interpolate(value, params);
    }

    // 翻译指定 key 并得到原始值（不插值），用于 data-i18n 属性
    _tRaw(key) {
        if (!key) return '';
        let value = this._getNestedValue(this._translations, key);
        if (value === undefined && this._currentLocale !== this.fallbackLocale && this._cache[this.fallbackLocale]) {
            value = this._getNestedValue(this._cache[this.fallbackLocale], key);
        }
        return value !== undefined ? value : key;
    }

    // 从嵌套对象中获取值，支持 a.b.c 格式
    _getNestedValue(obj, path) {
        if (!obj || !path) return undefined;
        const keys = path.split('.');
        let current = obj;
        for (const k of keys) {
            if (current === null || current === undefined) return undefined;
            current = current[k];
        }
        return current;
    }

    // 插值替换 {{variable}}
    _interpolate(template, params) {
        if (typeof template !== 'string') return template;
        return template.replace(/\{\{(\w+)\}\}/g, (match, key) => {
            return params[key] !== undefined ? params[key] : match;
        });
    }

    // 将翻译应用到 DOM 中所有带 data-i18n 属性的元素
    _applyToDOM() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.dataset.i18n;
            const value = this._tRaw(key);
            if (!value) return;

            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                if (el.type === 'placeholder' || el.hasAttribute('placeholder')) {
                    el.placeholder = value;
                } else {
                    el.value = value;
                }
            } else if (el.tagName === 'IMG') {
                el.alt = value;
            } else {
                // 保留原子元素不被替换
                if (el.children.length > 0 && !el.querySelector('strong,em,span,a,button')) {
                    el.textContent = value;
                } else {
                    // 安全更新：只替换文本节点
                    this._updateTextNodes(el, value);
                }
            }
        });
    }

    // 更新元素的文本节点，保留 HTML 子元素
    _updateTextNodes(el, text) {
        // 如果元素包含子元素（如 strong），先尝试替换第一个文本节点
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
        const textNodes = [];
        while (walker.nextNode()) {
            textNodes.push(walker.currentNode);
        }
        if (textNodes.length === 1) {
            textNodes[0].textContent = text;
        } else if (textNodes.length > 1) {
            // 多个文本节点，合并到第一个
            textNodes[0].textContent = text;
            for (let i = 1; i < textNodes.length; i++) {
                textNodes[i].textContent = '';
            }
        }
    }

    // 更新语言选择下拉框
    _updateLangToggle() {
        const select = document.getElementById('lang-select');
        if (!select) return;
        select.value = this._currentLocale;
    }

    _syncLocaleToServer(locale) {
        try {
            fetch('/api/i18n/language', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ locale })
            }).catch(() => {});
        } catch (e) {
            console.warn('[I18n] Failed to sync locale to server', e);
        }
    }

    // 监听语言切换
    onChange(callback) {
        if (typeof callback === 'function') {
            this._changeCallbacks.push(callback);
        }
    }

    _fireChangeCallbacks() {
        this._changeCallbacks.forEach(cb => {
            try { cb(this._currentLocale); } catch (e) { console.error(e); }
        });
    }

    // ============ 格式化工具 ============

    // 日期格式化：根据当前语言返回格式化后的日期字符串
    formatDate(date, formatKey = 'short') {
        const d = date instanceof Date ? date : new Date(date);
        if (isNaN(d.getTime())) return '';
        const fmt = this.t('dateFormat.' + formatKey);
        const localeMap = { 'zh': 'zh-CN', 'en': 'en-US', 'ja': 'ja-JP', 'ko': 'ko-KR' };
        const jsLocale = localeMap[this._currentLocale] || 'en-US';

        // 使用 Intl.DateTimeFormat 进行原生格式化
        const options = this._getDateFormatOptions(formatKey);
        try {
            return new Intl.DateTimeFormat(jsLocale, options).format(d);
        } catch (e) {
            return d.toLocaleDateString();
        }
    }

    formatDateTime(date, formatKey = 'long') {
        const d = date instanceof Date ? date : new Date(date);
        if (isNaN(d.getTime())) return '';
        const localeMap = { 'zh': 'zh-CN', 'en': 'en-US', 'ja': 'ja-JP', 'ko': 'ko-KR' };
        const jsLocale = localeMap[this._currentLocale] || 'en-US';
        const options = this._getDateTimeFormatOptions(formatKey);
        try {
            return new Intl.DateTimeFormat(jsLocale, options).format(d);
        } catch (e) {
            return d.toLocaleString();
        }
    }

    _getDateFormatOptions(formatKey) {
        switch (formatKey) {
            case 'short': return { year: 'numeric', month: '2-digit', day: '2-digit' };
            case 'long': return { year: 'numeric', month: 'long', day: 'numeric' };
            default: return { year: 'numeric', month: '2-digit', day: '2-digit' };
        }
    }

    _getDateTimeFormatOptions(formatKey) {
        switch (formatKey) {
            case 'short': return { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' };
            case 'long': return { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };
            default: return { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' };
        }
    }

    // 相对时间格式化
    formatRelativeTime(date) {
        const d = date instanceof Date ? date : new Date(date);
        if (isNaN(d.getTime())) return '';
        const now = new Date();
        const diffMs = now - d;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHour / 24);
        const diffWeek = Math.floor(diffDay / 7);

        if (diffSec < 60) return this.t('dateFormat.relative.justNow');
        if (diffMin < 60) return this.t('dateFormat.relative.minutesAgo', { n: diffMin });
        if (diffHour < 24) return this.t('dateFormat.relative.hoursAgo', { n: diffHour });
        if (diffDay < 7) return this.t('dateFormat.relative.daysAgo', { n: diffDay });
        if (diffWeek < 4) return this.t('dateFormat.relative.weeksAgo', { n: diffWeek });
        return this.formatDate(d, 'short');
    }

    // 数字格式化：千分位、小数点
    formatNumber(num, decimals = 0) {
        const localeMap = { 'zh': 'zh-CN', 'en': 'en-US', 'ja': 'ja-JP', 'ko': 'ko-KR' };
        const jsLocale = localeMap[this._currentLocale] || 'en-US';
        try {
            return new Intl.NumberFormat(jsLocale, {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals
            }).format(num);
        } catch (e) {
            return num.toLocaleString();
        }
    }

    // 货币格式化
    formatCurrency(amount, currency = 'CNY') {
        const localeMap = { 'zh': 'zh-CN', 'en': 'en-US', 'ja': 'ja-JP', 'ko': 'ko-KR' };
        const jsLocale = localeMap[this._currentLocale] || 'en-US';
        const currencyMap = { 'zh': 'CNY', 'en': 'USD', 'ja': 'JPY', 'ko': 'KRW' };
        const cur = currency || currencyMap[this._currentLocale] || 'CNY';
        try {
            return new Intl.NumberFormat(jsLocale, {
                style: 'currency',
                currency: cur,
                minimumFractionDigits: cur === 'JPY' || cur === 'KRW' ? 0 : 2
            }).format(amount);
        } catch (e) {
            return amount.toFixed(2);
        }
    }
}

// 全局 i18n 实例
const i18n = new I18n({
    fallbackLocale: 'zh'
});

class SmartCodeApp {
    constructor() {
        this.currentType = null;
        this.urlSubType = 'static';
        this.history = [];
        this.batchQrcodes = [];
        this.currentQrcode = null;
        this.logoPath = null;
        this.isAuthenticated = false;
        this.currentUser = null;
        
        this.init();
    }

    async init() {
        window.qrApp = this;
        window.app = this;
        // 初始化 i18n
        await i18n.init();
        // 监听语言切换，切换后重绘动态内容
        i18n.onChange(() => {
            this.refreshCurrentTab();
        });
        this.checkAuthentication();
        this.setupEventListeners();
        this.updateInputContainer();
        this.hideResultStage();
        this.setupHistory();
        this.loadTemplates();
        this.loadHistory();
        this.loadWorkspace();
        this.initTheme();

        // 点击外部关闭下拉菜单
        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('top-nav-dropdown');
            const moreBtn = document.getElementById('nav-more-btn');
            if (dropdown && dropdown.classList.contains('show') &&
                !dropdown.contains(e.target) && !moreBtn.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });
    }

    // 切换语言：下拉选择指定语言
    changeLanguage(locale) {
        i18n.setLocale(locale);
    }

    // 翻译快捷方法
    t(key, params) {
        return i18n.t(key, params);
    }

    // 刷新当前标签页内容（语言切换后触发）
    refreshCurrentTab() {
        const activeTab = document.querySelector('.top-nav-item.active');
        if (!activeTab) return;
        const tab = activeTab.dataset.tab;
        const tabMap = {
            'workspace': () => this.loadWorkspace(),
            'history': () => this.loadHistory(),
            'templates': () => this.loadTemplates(),
            'lifecycle': () => this.loadLifecycleList(),
            'org': () => this.loadOrgTree(),
            'openplatform': () => this.openplatformLoadApps(),
            'workflow': () => this.workflowLoadList(),
            'subscription': () => this.subscriptionLoad(),
            'revenue': () => this.revenueLoad(),
            'audit': () => this.loadAuditLogs(1),
            'recycle': () => this.loadRecycle(1)
        };
        if (tabMap[tab]) {
            tabMap[tab].call(this);
        }
    }

    // ============ 认证相关 ============
    
    async checkAuthentication() {
        // 检查用户认证状态
        try {
            const response = await fetch('/api/check_auth');
            const data = await response.json();
            
            if (data.authenticated) {
                this.isAuthenticated = true;
                this.currentUser = {
                    id: data.user_id,
                    username: data.username
                };
                this.showLoggedInUI();
            } else {
                this.showLoginUI();
            }
        } catch (error) {
            console.error('检查认证失败:', error);
            this.showLoginUI();
        }
    }

    showLoggedInUI() {
        // 显示已登录UI
        const loggedInDiv = document.getElementById('user-logged-in');
        const loginBtn = document.getElementById('login-btn');
        
        if (loggedInDiv && loginBtn) {
            document.getElementById('username-display').textContent = this.t('error.welcome', { username: this.currentUser.username });
            loggedInDiv.style.display = 'flex';
            loginBtn.style.display = 'none';
            
            document.getElementById('logout-btn').addEventListener('click', () => this.logout());
        }
        // 更新顶部导航头像
        const avatarInitial = document.getElementById('nav-avatar-initial');
        if (avatarInitial && this.currentUser && this.currentUser.username) {
            avatarInitial.textContent = this.currentUser.username.charAt(0).toUpperCase();
        }
        this.loadWorkspace();
    }

    showLoginUI() {
        // 显示未登录UI
        const loggedInDiv = document.getElementById('user-logged-in');
        const loginBtn = document.getElementById('login-btn');
        
        if (loggedInDiv && loginBtn) {
            loggedInDiv.style.display = 'none';
            loginBtn.style.display = 'block';
            
            loginBtn.addEventListener('click', () => {
                document.getElementById('auth-modal').classList.add('active');
            });
        }
    }

    switchAuthTab(tab) {
        // 切换登录/注册标签
        if (tab === 'login') {
            document.getElementById('login-form-container').style.display = 'block';
            document.getElementById('register-form-container').style.display = 'none';
        } else {
            document.getElementById('login-form-container').style.display = 'none';
            document.getElementById('register-form-container').style.display = 'block';
        }
    }

    async login(username, password) {
        // 执行登录
        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            const data = await response.json();

            if (data.success) {
                this.isAuthenticated = true;
                this.currentUser = {
                    id: data.user_id,
                    username: data.username
                };
                this.showLoggedInUI();
                document.getElementById('auth-modal').classList.remove('active');
                this.showNotification('auth.loginSuccess', 'success');
                return true;
            } else {
                this.showNotification(data.error, 'error');
                return false;
            }
        } catch (error) {
            console.error('登录失败:', error);
            this.showNotification('auth.loginFailed', 'error');
            return false;
        }
    }

    async register(username, email, password, confirmPassword) {
        // 执行注册
        if (password !== confirmPassword) {
            this.showNotification('error.passwordMismatch', 'error');
            return false;
        }

        try {
            const response = await fetch('/api/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, email, password })
            });

            const data = await response.json();

            if (data.success) {
                this.isAuthenticated = true;
                this.currentUser = {
                    id: data.user_id,
                    username: data.username
                };
                this.showLoggedInUI();
                document.getElementById('auth-modal').classList.remove('active');
                this.showNotification('auth.registerSuccess', 'success');
                return true;
            } else {
                this.showNotification(data.error, 'error');
                return false;
            }
        } catch (error) {
            console.error('注册失败:', error);
            this.showNotification('auth.registerFailed', 'error');
            return false;
        }
    }

    async logout() {
        // 执行登出
        try {
            const response = await fetch('/api/logout', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                this.isAuthenticated = false;
                this.currentUser = null;
                this.showLoginUI();
                this.showNotification('error.loggedOut', 'success');
            }
        } catch (error) {
            console.error('登出失败:', error);
            this.showNotification('error.logoutFailed', 'error');
        }
    }

    setupEventListeners() {
        // 登录注册表单
        const loginForm = document.getElementById('login-form');
        if (loginForm) {
            loginForm.addEventListener('submit', (e) => {
                e.preventDefault();
                const username = document.getElementById('login-username').value;
                const password = document.getElementById('login-password').value;
                this.login(username, password);
            });
        }

        const registerForm = document.getElementById('register-form');
        if (registerForm) {
            registerForm.addEventListener('submit', (e) => {
                e.preventDefault();
                const username = document.getElementById('register-username').value;
                const email = document.getElementById('register-email').value;
                const password = document.getElementById('register-password').value;
                const confirmPassword = document.getElementById('register-confirm-password').value;
                this.register(username, email, password, confirmPassword);
            });
        }

        // 模态框关闭
        document.getElementById('auth-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'auth-modal') {
                document.getElementById('auth-modal').classList.remove('active');
            }
        });

        // 类型选择
        document.querySelectorAll('.type-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchType(btn));
        });

        // 标签页切换 - 顶部导航
        document.querySelectorAll('.top-nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const tab = item.dataset.tab;
                if (tab) this.switchTab(tab);
            });
        });

        // 标签页切换 - 下拉菜单中的导航项
        document.querySelectorAll('.top-nav-dropdown-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const tab = item.dataset.tab;
                if (tab) {
                    this.switchTab(tab);
                    // 关闭下拉菜单
                    document.getElementById('top-nav-dropdown').classList.remove('show');
                }
            });
        });

        // 样式选择
        document.querySelectorAll('.style-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchStyle(btn));
        });

        // 生成按钮
        document.getElementById('generate-btn').addEventListener('click', () => this.generate());

        // 颜色选择
        document.getElementById('fill-color').addEventListener('change', (e) => {
            document.getElementById('fill-color-value').textContent = e.target.value;
        });

        document.getElementById('back-color').addEventListener('change', (e) => {
            document.getElementById('back-color-value').textContent = e.target.value;
        });

        // 滑块
        document.getElementById('box-size').addEventListener('input', (e) => {
            document.getElementById('box-size-value').textContent = e.target.value;
        });

        // Logo上传
        document.getElementById('logo-input').addEventListener('change', (e) => this.handleLogoUpload(e));

        // 下载按钮
        document.getElementById('download-png-btn').addEventListener('click', () => this.downloadQrcode('png'));
        document.getElementById('download-svg-btn').addEventListener('click', () => this.downloadQrcode('svg'));
        document.getElementById('copy-btn').addEventListener('click', () => this.copyQrcode());

        // 批量处理
        document.getElementById('batch-file').addEventListener('change', (e) => this.handleBatchFile(e));
        document.getElementById('batch-generate-btn').addEventListener('click', () => this.generateBatch());
        document.getElementById('download-all-btn').addEventListener('click', () => this.downloadBatchAll());

        // 文件上传拖放
        this.setupDragDrop();
        const backBtn = document.getElementById('back-to-config-btn');
        if (backBtn) {
            backBtn.addEventListener('click', () => window.history.back());
        }
        // 模态框关闭
        document.querySelector('.modal-close')?.addEventListener('click', () => this.closeModal());
        document.getElementById('modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'modal') this.closeModal();
        });
    }

    switchType(btn) {
        document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.currentType = btn.dataset.type;
        if (this.currentType === 'url') this.urlSubType = 'static';
        this.updateInputContainer();
    }

    updateInputContainer() {
        const t = (k, p) => this.t(k, p);
        const rt = (k) => this.t('richEditor.' + k);
        const container = document.getElementById('input-container');
        const types = {
            text: `<div class="card-header-row"><h3 style="margin:0">${t('error.inputContent')}</h3><button class="btn-text" id="toggle-rich-editor" onclick="window.qrApp.toggleRichEditor()">${t('error.complexEdit')}</button></div><textarea id="content-input" class="input-field" placeholder="${t('error.inputContentPlaceholder')}" rows="4"></textarea><div id="rich-editor-container" class="hidden"><div class="rich-toolbar"><select onchange="document.execCommand('fontSize',false,this.value)" class="rich-select"><option value="1">${rt('fontSmall')}</option><option value="3" selected>${rt('fontMedium')}</option><option value="5">${rt('fontLarge')}</option><option value="7">${rt('fontXLarge')}</option></select><button onclick="document.execCommand('bold')" title="${rt('bold')}"><b>B</b></button><button onclick="document.execCommand('italic')" title="${rt('italic')}"><i>I</i></button><button onclick="document.execCommand('underline')" title="${rt('underline')}"><u>U</u></button><input type="color" onchange="document.execCommand('foreColor',false,this.value)" title="${rt('textColor')}"><button onclick="document.execCommand('justifyLeft')" title="${rt('alignLeft')}">≡</button><button onclick="document.execCommand('justifyCenter')" title="${rt('alignCenter')}">≡</button><button onclick="document.execCommand('justifyRight')" title="${rt('alignRight')}">≡</button><button onclick="document.execCommand('insertUnorderedList')" title="${rt('unorderedList')}">•</button><button onclick="document.execCommand('insertOrderedList')" title="${rt('orderedList')}">1.</button><button onclick="const u=prompt('${rt('imageUrlPrompt')}');if(u)document.execCommand('insertImage',false,u)" title="${rt('insertImage')}">图</button><button onclick="const u=prompt('${rt('linkUrlPrompt')}');if(u)document.execCommand('createLink',false,u)" title="${rt('insertLink')}">链</button><button onclick="const u=prompt('${rt('videoUrlPrompt')}');if(u)document.execCommand('insertHTML',false,'<video src='+u+' controls width=100%></video>')" title="${rt('insertVideo')}">视</button></div><div id="rich-editor" class="rich-editor" contenteditable="true"></div></div>`,
            url: `<div>
                <div class="url-sub-types">
                    <button class="url-sub-btn active" data-urlsub="static" onclick="window.qrApp.selectUrlSub(event, 'static')">${t('error.staticCode')}</button>
                    <button class="url-sub-btn" data-urlsub="redirect" onclick="window.qrApp.selectUrlSub(event, 'redirect')">${t('error.redirectCode')}</button>
                    <button class="url-sub-btn" data-urlsub="multi" onclick="window.qrApp.selectUrlSub(event, 'multi')">${t('error.multiUrl')}</button>
                </div>
                <div id="url-static-panel"><input type="url" class="input-field" placeholder="${t('error.urlPlaceholder')}" id="url-input" style="margin-top:10px"></div>
                <div id="url-redirect-panel" class="hidden"><input type="url" class="input-field" placeholder="${t('error.targetUrlPlaceholder')}" id="url-redirect-input" style="margin-top:10px"><p class="hint-text" style="margin-top:4px">${t('error.redirectHint')}</p></div>
                <div id="url-multi-panel" class="hidden"><div id="url-multi-list"><input type="url" class="input-field url-multi-input" placeholder="${t('error.urlNumber', { n: 1 })}" style="margin-top:10px"></div><button class="btn-text" onclick="window.qrApp.addUrlField()" style="margin-top:8px">+ ${t('error.addUrl')}</button></div>
            </div>`,
            email: `<div>
                <input type="email" class="input-field" placeholder="${t('error.emailPlaceholder')}" id="email-input">
                <input type="text" class="input-field" placeholder="${t('error.subjectPlaceholder')}" id="subject-input" style="margin-top: 10px;">
                <textarea class="input-field" placeholder="${t('error.mailBody')}" id="body-input" rows="3" style="margin-top: 10px;"></textarea>
            </div>`,
vcard: `<div>
                <input type="text" class="input-field" placeholder="${t('error.namePlaceholder')}" id="vcard-name">
                <input type="text" class="input-field" placeholder="${t('error.titlePlaceholder')}" id="vcard-title" style="margin-top: 10px;">
                <input type="tel" class="input-field" placeholder="${t('error.phonePlaceholder')}" id="vcard-phone" style="margin-top: 10px;">
                <input type="email" class="input-field" placeholder="${t('error.emailPlaceholder2')}" id="vcard-email" style="margin-top: 10px;">
                <input type="text" class="input-field" placeholder="${t('error.companyPlaceholder')}" id="vcard-company" style="margin-top: 10px;">
            </div>`,
            wifi: `<div>
                <input type="text" class="input-field" placeholder="${t('error.ssidPlaceholder')}" id="wifi-ssid">
                <input type="password" class="input-field" placeholder="${t('error.passwordPlaceholder')}" id="wifi-password" style="margin-top: 10px;">
                <select id="wifi-security" class="select-field" style="margin-top: 10px;">
                    <option value="WPA">WPA</option>
                    <option value="WEP">WEP</option>
                    <option value="nopass">${t('error.noPassword')}</option>
                </select>
            </div>`,
            questionnaire: `<div class="card-header-row"><h3 style="margin:0">${t('error.inputContent')}</h3><button class="btn-text" id="toggle-form-editor" onclick="window.qrApp.toggleFormEditor()" style="color:#38BDF8;font-weight:600">${t('error.advancedEdit')}</button></div><textarea id="content-input" class="input-field" placeholder="${t('error.surveyInputHint')}" rows="4"></textarea><input type="hidden" id="form-schema-json" value="">`,
            form: `<div class="card-header-row"><h3 style="margin:0">${t('error.inputContent')}</h3><button class="btn-text" id="toggle-form-editor" onclick="window.qrApp.toggleFormEditor()" style="color:#38BDF8;font-weight:600">${t('error.advancedEdit')}</button></div><textarea id="content-input" class="input-field" placeholder="${t('error.formInputHint')}" rows="4"></textarea><input type="hidden" id="form-schema-json" value="">`,
            file: `<div class="upload-box" id="upload-box"><input type="file" id="file-input" onchange="window.qrApp.onFileSelect(event)"><p class="upload-info" id="upload-info"></p></div>`,
            image: `<div class="upload-box" id="upload-box"><input type="file" id="file-input" onchange="window.qrApp.onFileSelect(event)"><p class="upload-info" id="upload-info"></p></div>`,
            media: `<div class="upload-box" id="upload-box"><input type="file" id="file-input" onchange="window.qrApp.onFileSelect(event)"><p class="upload-info" id="upload-info"></p></div>`
        };

        if (!this.currentType) {
            container.innerHTML = `<textarea id="content-input" class="input-field" placeholder="${t('error.selectTypeHint2')}" rows="4"></textarea>`;
        } else {
            container.innerHTML = types[this.currentType] || types.text;
        }

        const uploadCfg = {
            file: { accept: '.zip,.doc,.docx,.pdf,.xls,.xlsx,.ppt,.pptx,.txt,.csv', info: t('error.fileInfo'), multiple: '' },
            image: { accept: 'image/png,image/jpeg,image/gif,image/webp,image/svg+xml', info: t('error.imageInfo'), multiple: 'multiple' },
            media: { accept: 'video/mp4,video/avi,video/mov,video/x-matroska,audio/mpeg,audio/wav,audio/flac,audio/mp4', info: t('error.mediaInfo'), multiple: '' }
        };
        const cfg = uploadCfg[this.currentType];
        if (cfg) {
            const fi = document.getElementById('file-input');
            const ui = document.getElementById('upload-info');
            if (fi) { fi.accept = cfg.accept; if (cfg.multiple) fi.setAttribute('multiple', ''); }
            if (ui) ui.innerHTML = cfg.info;
        }
    }

    hideResultStage() {
        document.getElementById('result-stage')?.classList.add('hidden');
        document.getElementById('config-stage')?.classList.remove('hidden');
    }

    showResultStage() {
        const resultStage = document.getElementById('result-stage');
        document.getElementById('result-stage')?.classList.remove('hidden');
        document.getElementById('config-stage')?.classList.add('hidden');
        resultStage?.scrollIntoView({ behavior: 'smooth' });
    }

    setupHistory() {
        window.history.replaceState({ view: 'config' }, '');
        this._onPopState = (event) => {
            const view = event.state?.view || 'config';
            if (view === 'result') {
                this.showResultStage();
            } else {
                this.hideResultStage();
            }
        };
        window.addEventListener('popstate', this._onPopState);
    }

    destroy() {
        window.removeEventListener('popstate', this._onPopState);
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
        }
        if (this._notifPollTimer) {
            clearInterval(this._notifPollTimer);
        }
    }

    switchStyle(btn) {
        document.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    }

    switchTab(tab) {
        // 更新顶部主导航
        document.querySelectorAll('.top-nav-item').forEach(item => item.classList.remove('active'));
        const mainNavItem = document.querySelector(`.top-nav-item[data-tab="${tab}"]`);
        if (mainNavItem) mainNavItem.classList.add('active');

        // 更新下拉菜单中的导航项
        document.querySelectorAll('.top-nav-dropdown-item').forEach(item => item.classList.remove('active'));
        const dropdownItem = document.querySelector(`.top-nav-dropdown-item[data-tab="${tab}"]`);
        if (dropdownItem) dropdownItem.classList.add('active');

        // 更新标签页
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        const targetEl = document.getElementById(`${tab}-tab`);
        if (!targetEl) {
            console.warn(`switchTab: 找不到标签元素 target=${tab}-tab`);
            return;
        }
        targetEl.classList.add('active');

        // 更新标题
        const titles = {
            workspace: { title: this.t('workspace.title'), subtitle: this.t('workspace.subtitle') },
            generator: { title: this.t('nav.generator'), subtitle: this.t('nav.generatorSubtitle') },
            batch: { title: this.t('nav.batch'), subtitle: this.t('nav.batchSubtitle') },
            history: { title: this.t('nav.history'), subtitle: this.t('nav.historySubtitle') },
            templates: { title: this.t('nav.templates'), subtitle: this.t('nav.templatesSubtitle') },
            lifecycle: { title: this.t('nav.lifecycle'), subtitle: this.t('nav.lifecycleSubtitle') },
            recycle: { title: this.t('nav.recycle'), subtitle: this.t('nav.recycleSubtitle') },
            org: { title: this.t('nav.org'), subtitle: this.t('nav.orgSubtitle') },
            subscription: { title: this.t('nav.subscription'), subtitle: this.t('nav.subscriptionSubtitle') },
            revenue: { title: this.t('nav.revenue'), subtitle: this.t('nav.revenueSubtitle') }
        };
        const titleData = titles[tab] || titles.generator;
        const pageTitle = document.getElementById('page-title');
        const pageSubtitle = document.getElementById('page-subtitle');
        if (pageTitle) pageTitle.textContent = titleData.title;
        if (pageSubtitle) pageSubtitle.textContent = titleData.subtitle;

        if (tab === 'workspace') {
            this.loadWorkspace();
        }
        if (tab === 'lifecycle') {
            this.loadLifecycleList();
        }
        if (tab === 'audit') {
            this.loadAuditFilters();
            this.loadAuditLogs();
        }
        if (tab === 'recycle') {
            this.loadRecycle();
        }
        if (tab === 'org') {
            this.orgLoadTree();
        }
        if (tab === 'openplatform') {
            this.openplatformLoadApps();
        }
        if (tab === 'workflow') {
            this.workflowLoadList();
        }
        if (tab === 'subscription') {
            this.subscriptionLoad();
        }
        if (tab === 'revenue') {
            this.revenueLoad();
        }
    }

    toggleMoreMenu() {
        const dropdown = document.getElementById('top-nav-dropdown');
        if (dropdown) {
            dropdown.classList.toggle('show');
        }
    }

    toggleUserMenu() {
        if (this.currentUser) {
            // 已登录：显示登出选项
            document.getElementById('auth-modal').classList.add('active');
        } else {
            document.getElementById('auth-modal').classList.add('active');
        }
    }

    focusSearch() {
        // 切换到二维码生成页并聚焦到内容输入框
        this.switchTab('generator');
        setTimeout(() => {
            const input = document.getElementById('content-input');
            if (input) input.focus();
        }, 300);
    }

    openNotifications() {
        // 简单的通知面板
        this.showNotification('暂无新通知', 'info');
    }

    async generate() {
        if (!this.currentType) {
            this.showNotification('error.selectType', 'error');
            return;
        }

        if (['file', 'image', 'media'].includes(this.currentType)) {
            const fileInput = document.getElementById('file-input');
            if (!fileInput?.files?.length) {
                this.showNotification('error.noFileSelected', 'error');
                return;
            }
            this.showNotification('error.uploading', 'info');
            const url = await this.uploadFile(fileInput.files[0]);
            if (!url) return;
            this.uploadedUrl = url;
        }

        const content = this.getContentFromInput();
        if (!content || (typeof content === 'string' && !content.trim())) {
            this.showNotification('请输入内容', 'error');
            return;
        }

        this.showNotification('生成中...', 'info');

        try {
            const response = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: content,
                    type: this.currentType,
                    config: this.getConfig()
                })
            });

            const data = await response.json();

            if (data.success) {
                this.currentQrcode = {
                    content: content,
                    type: this.currentType,
                    image: data.qrcode,
                    timestamp: data.timestamp
                };
                this.showResultStage();
                window.history.pushState({ view: 'result' }, '');
                this.displayQrcode(data.qrcode);
                this.addToHistory(content, data.qrcode);
                this.showNotification('生成成功！', 'success');
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (error) {
            console.error('Error:', error);
            this.showNotification('error.generateFailed', 'error');
        }
    }

    async uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) return data.url;
            this.showNotification(data.error || this.t('toast.uploadFailed', '上传失败'), 'error');
            return null;
        } catch (e) {
            this.showNotification('error.uploadFailed', 'error');
            return null;
        }
    }

    onFileSelect(event) {
        const file = event.target.files[0];
        if (file) {
            document.querySelector('.upload-box').classList.add('has-file');
        }
    }

    selectUrlSub(event, type) {
        this.urlSubType = type;
        document.querySelectorAll('.url-sub-btn').forEach(b => b.classList.remove('active'));
        event.target.classList.add('active');
        ['static', 'redirect', 'multi'].forEach(t => {
            const panel = document.getElementById(`url-${t}-panel`);
            if (panel) panel.classList.toggle('hidden', t !== type);
        });
    }

    addUrlField() {
        const list = document.getElementById('url-multi-list');
        const i = list.children.length + 1;
        const input = document.createElement('input');
        input.type = 'url';
        input.className = 'input-field url-multi-input';
        input.placeholder = `网址${i}`;
        input.style.marginTop = '8px';
        list.appendChild(input);
    }

    toggleRichEditor() {
        const inputContainer = document.getElementById('input-container');
        const richContainer = document.getElementById('rich-editor-container');
        const toggleBtn = document.getElementById('toggle-rich-editor');
        const isRich = !richContainer.classList.contains('hidden');
        if (isRich) {
            richContainer.classList.add('hidden');
            inputContainer.classList.remove('hidden');
            toggleBtn.textContent = '复杂编辑';
            toggleBtn.classList.remove('active');
        } else {
            const cur = document.getElementById('content-input');
            if (cur && cur.value) {
                document.getElementById('rich-editor').innerHTML = cur.value;
            }
            richContainer.classList.remove('hidden');
            inputContainer.classList.add('hidden');
            toggleBtn.textContent = '简易编辑';
            toggleBtn.classList.add('active');
        }
    }

    getContentFromInput() {
        const types = {
            text: () => document.getElementById('content-input')?.value || '',
            url: () => {
                if (this.urlSubType === 'multi') {
                    const urls = [...document.querySelectorAll('.url-multi-input')].map(i => i.value).filter(Boolean);
                    return urls.length ? urls.join('\n') : '';
                }
                if (this.urlSubType === 'redirect') {
                    return document.getElementById('url-redirect-input')?.value || '';
                }
                return document.getElementById('url-input')?.value || '';
            },
            email: () => ({
                email: document.getElementById('email-input')?.value || '',
                subject: document.getElementById('subject-input')?.value || '',
                body: document.getElementById('body-input')?.value || ''
            }),
vcard: () => ({
                name: document.getElementById('vcard-name')?.value || '',
                title: document.getElementById('vcard-title')?.value || '',
                phone: document.getElementById('vcard-phone')?.value || '',
                email: document.getElementById('vcard-email')?.value || '',
                company: document.getElementById('vcard-company')?.value || ''
            }),
            wifi: () => ({
                ssid: document.getElementById('wifi-ssid')?.value || '',
                password: document.getElementById('wifi-password')?.value || '',
                security: document.getElementById('wifi-security')?.value || 'WPA'
            }),
            questionnaire: () => {
                const schema = document.getElementById('form-schema-json')?.value;
                if (schema) return schema;
                return document.getElementById('content-input')?.value || '';
            },
            form: () => document.getElementById('content-input')?.value || '',
            file: () => this.uploadedUrl || '',
            image: () => this.uploadedUrl || '',
            media: () => this.uploadedUrl || ''
        }

        const getter = types[this.currentType] || types.text;
        const richEditor = document.getElementById('rich-editor');
        if (richEditor && !richEditor.parentElement.classList.contains('hidden')) {
            return richEditor.innerHTML || '';
        }
        return getter();
    }

    getConfig() {
        const style = document.querySelector('.style-btn.active')?.dataset.style || 'square';
        return {
            style: style,
            fill_color: document.getElementById('fill-color').value,
            back_color: document.getElementById('back-color').value,
            box_size: parseInt(document.getElementById('box-size').value),
            error_correction: document.getElementById('error-correction').value,
            logo_path: this.logoPath
        };
    }

    displayQrcode(imageData) {
        const preview = document.getElementById('qrcode-preview');
        preview.innerHTML = `<img src="${imageData}" alt="二维码">`;

        const previewContent = document.getElementById('preview-content');
        const content = this.currentQrcode?.content;
        if (typeof content === 'string') {
            previewContent.textContent = `内容: ${content.substring(0, 50)}${content.length > 50 ? '...' : ''}`;
        } else {
            previewContent.textContent = '二维码已生成';
        }

        this.updatePhonePreview();
    }

    updatePhonePreview() {
        const phoneScreen = document.getElementById('phone-screen');
        if (!phoneScreen || !this.currentQrcode) return;

        const type = this.currentQrcode.type;
        const content = this.currentQrcode.content;

        let html = '';

        switch (type) {
            case 'url':
                html = this.buildUrlPreview(content);
                break;
            case 'text':
                html = this.buildTextPreview(content);
                break;
            case 'vcard':
                html = this.buildVcardPreview(content);
                break;
            case 'wifi':
                html = this.buildWifiPreview(content);
                break;
            case 'email':
                html = this.buildEmailPreview(content);
                break;
            case 'questionnaire':
                html = this.buildQuestionnairePreview(content);
                break;
            case 'form':
                html = this.buildFormPreview(content);
                break;
            default:
                html = this.buildTextPreview(content);
        }

        phoneScreen.innerHTML = `<div class="phone-screen-content">${html}</div>`;
    }

    buildUrlPreview(url) {
        const displayUrl = typeof url === 'string' ? url : '';
        return `
            <div class="phone-browser-bar">${displayUrl.substring(0, 30)}${displayUrl.length > 30 ? '...' : ''}</div>
            <div class="phone-title">网页链接</div>
            <div class="phone-body">扫描后将打开以下网址：<br><br><strong>${displayUrl}</strong></div>
        `;
    }

    buildTextPreview(text) {
        const displayText = typeof text === 'string' ? text : JSON.stringify(text);
        return `
            <div class="phone-title">文本内容</div>
            <div class="phone-body">${displayText.replace(/</g, '&lt;').replace(/>/g, '&gt;').substring(0, 200)}${displayText.length > 200 ? '...' : ''}</div>
        `;
    }

    buildVcardPreview(vcard) {
        return `
            <div class="phone-title">名片</div>
            <div class="phone-card-inner">
                <div class="phone-label">姓名</div>
                <div class="phone-value">${vcard.name || '-'}</div>
            </div>
            <div class="phone-card-inner">
                <div class="phone-label">电话</div>
                <div class="phone-value">${vcard.phone || '-'}</div>
            </div>
            <div class="phone-card-inner">
                <div class="phone-label">邮箱</div>
                <div class="phone-value">${vcard.email || '-'}</div>
            </div>
            <div class="phone-card-inner">
                <div class="phone-label">公司</div>
                <div class="phone-value">${vcard.company || '-'}</div>
            </div>
            <div class="phone-body" style="text-align:center;margin-top:8px;color:#4a9bc8;">[ 添加到通讯录 ]</div>
        `;
    }

    buildWifiPreview(wifi) {
        return `
            <div class="phone-title">WiFi 网络</div>
            <div class="phone-card-inner">
                <div class="phone-label">网络名称</div>
                <div class="phone-value">${wifi.ssid || '-'}</div>
            </div>
            <div class="phone-card-inner">
                <div class="phone-label">密码</div>
                <div class="phone-value">${'•'.repeat(Math.min(wifi.password ? wifi.password.length : 0, 12)) || '-'}</div>
            </div>
            <div class="phone-card-inner">
                <div class="phone-label">加密方式</div>
                <div class="phone-value">${wifi.security || 'WPA'}</div>
            </div>
            <div class="phone-body" style="text-align:center;margin-top:8px;color:#4a9bc8;">[ 加入网络 ]</div>
        `;
    }

    buildEmailPreview(email) {
        return `
            <div class="phone-title">邮件</div>
            <div class="phone-card-inner">
                <div class="phone-label">收件人</div>
                <div class="phone-value">${email.email || '-'}</div>
            </div>
            <div class="phone-card-inner">
                <div class="phone-label">主题</div>
                <div class="phone-value">${email.subject || '-'}</div>
            </div>
            <div class="phone-card-inner">
                <div class="phone-label">正文</div>
                <div class="phone-value">${(email.body || '-').substring(0, 60)}${(email.body || '').length > 60 ? '...' : ''}</div>
            </div>
            <div class="phone-body" style="text-align:center;margin-top:8px;color:#4a9bc8;">[ 发送邮件 ]</div>
        `;
    }

    buildQuestionnairePreview(content) {
        const displayText = typeof content === 'string' ? content : JSON.stringify(content);
        let schema = null;
        try { schema = JSON.parse(displayText); } catch (e) {}
        if (schema && schema.fields && Array.isArray(schema.fields)) {
            const fieldPreviews = schema.fields.slice(0, 5).map(f => {
                let input = '';
                switch (f.type) {
                    case 'text': input = `<input style="width:100%;padding:4px;border:1px solid #ddd;border-radius:3px;font-size:10px" placeholder="${f.placeholder || ''}">`; break;
                    case 'textarea': input = `<textarea style="width:100%;padding:4px;border:1px solid #ddd;border-radius:3px;font-size:10px" rows="2" placeholder="${f.placeholder || ''}"></textarea>`; break;
                    case 'radio': input = (f.options || []).map(o => `<span style="font-size:10px;margin-right:6px">○ ${o}</span>`).join(''); break;
                    case 'checkbox': input = (f.options || []).map(o => `<span style="font-size:10px;margin-right:6px">☐ ${o}</span>`).join(''); break;
                    case 'rating': input = '⭐'.repeat(f.max || 5); break;
                    case 'divider': input = '<hr style="border:none;border-top:1px solid #eee">'; break;
                    default: input = `<input style="width:100%;padding:4px;border:1px solid #ddd;border-radius:3px;font-size:10px" placeholder="${f.placeholder || ''}">`;
                }
                return `<div style="margin-bottom:6px"><div style="font-size:9px;font-weight:600;margin-bottom:2px">${f.label || ''}${f.required ? ' <span style="color:red">*</span>' : ''}</div>${input}</div>`;
            }).join('');
            const more = schema.fields.length > 5 ? `<div style="font-size:9px;color:#999;text-align:center">... 共 ${schema.fields.length} 个字段</div>` : '';
            return `<div class="phone-title">问卷表单</div><div class="phone-body" style="padding:8px">${fieldPreviews}${more}</div><div class="phone-body" style="text-align:center;margin-top:8px;color:#4a9bc8;">[ 提交问卷 ]</div>`;
        }
        return `
            <div class="phone-title">问卷</div>
            <div class="phone-body">扫描后将打开问卷链接</div>
            <div class="phone-card-inner" style="margin-top:10px;">
                <div class="phone-value" style="font-size:10px;color:#888;">${displayText.substring(0, 100)}${displayText.length > 100 ? '...' : ''}</div>
            </div>
            <div class="phone-body" style="text-align:center;margin-top:8px;color:#4a9bc8;">[ 开始填写 ]</div>
        `;
    }

    buildFormPreview(content) {
        const displayText = typeof content === 'string' ? content : JSON.stringify(content);
        return `
            <div class="phone-title">表格</div>
            <div class="phone-body">扫描后将打开表格</div>
            <div class="phone-card-inner" style="margin-top:10px;">
                <div class="phone-value" style="font-size:10px;color:#888;">${displayText.substring(0, 100)}${displayText.length > 100 ? '...' : ''}</div>
            </div>
            <div class="phone-body" style="text-align:center;margin-top:8px;color:#4a9bc8;">[ 查看表格 ]</div>
        `;
    }

    downloadQrcode(format) {
        if (!this.currentQrcode) {
            this.showNotification('请先生成二维码', 'error');
            return;
        }

        if (format === 'png') {
            const link = document.createElement('a');
            link.href = this.currentQrcode.image;
            link.download = `qrcode_${Date.now()}.png`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            this.showNotification(this.t('toast.downloadSuccess', '下载成功'), 'success');
        } else if (format === 'svg') {
            this.exportSvg();
        }
    }

    async exportSvg() {
        try {
            const response = await fetch('/api/export_svg', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: this.currentQrcode.content,
                    type: this.currentQrcode.type || 'text',
                    config: this.getConfig()
                })
            });

            const data = await response.json();
            if (data.success) {
                const blob = new Blob([data.svg], { type: 'image/svg+xml' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `qrcode_${Date.now()}.svg`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(url);
                this.showNotification('SVG下载成功！', 'success');
            }
        } catch (error) {
            this.showNotification(this.t('toast.exportSvgFailed', '导出SVG失败'), 'error');
        }
    }

    copyQrcode() {
        if (!this.currentQrcode?.image) {
            this.showNotification('请先生成二维码', 'error');
            return;
        }

        const canvas = document.createElement('canvas');
        const img = new Image();
        img.onload = () => {
            canvas.width = img.width;
            canvas.height = img.height;
            canvas.getContext('2d').drawImage(img, 0, 0);
            canvas.toBlob(blob => {
                navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
                    .then(() => this.showNotification('已复制到剪贴板', 'success'))
                    .catch(() => this.showNotification(this.t('toast.copyFailed', '复制失败'), 'error'));
            });
        };
        img.src = this.currentQrcode.image;
    }

    handleLogoUpload(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            const preview = document.getElementById('logo-preview');
            const img = document.getElementById('logo-img');
            img.src = event.target.result;
            preview.style.display = 'block';
        };
        reader.readAsDataURL(file);
    }

    handleBatchFile(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            const csv = event.target.result;
            this.parseCsvPreview(csv);
        };
        reader.readAsText(file);
    }

    parseCsvPreview(csv) {
        const lines = csv.split('\n').filter(line => line.trim());
        this.showNotification(`已加载 ${lines.length - 1} 条数据`, 'success');
    }

    async generateBatch() {
        const fileInput = document.getElementById('batch-file');
        const file = fileInput.files[0];

        if (!file) {
            this.showNotification('请选择CSV文件', 'error');
            return;
        }

        this.showNotification('批量生成中...', 'info');

        const formData = new FormData();
        formData.append('file', file);
        formData.append('config', JSON.stringify({
            style: document.getElementById('batch-style').value,
            fill_color: document.getElementById('batch-fill-color').value,
            back_color: document.getElementById('batch-back-color').value
        }));

        try {
            const response = await fetch('/api/generate_batch', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                this.batchQrcodes = data.qrcodes;
                this.displayBatchResults(data);
                this.showNotification(`成功生成 ${data.count} 个二维码！`, 'success');
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (error) {
            console.error('Error:', error);
            this.showNotification(this.t('toast.batchGenerateFailed', '批量生成失败'), 'error');
        }
    }

    displayBatchResults(data) {
        const resultsDiv = document.getElementById('batch-results');
        const grid = document.getElementById('batch-grid');
        const countInfo = document.getElementById('batch-count-info');

        countInfo.textContent = `已生成 ${data.count} 个二维码`;
        grid.innerHTML = '';

        data.qrcodes.forEach(qr => {
            const item = document.createElement('div');
            item.className = 'batch-item';
            item.innerHTML = `
                <img src="${qr.qrcode}" alt="二维码">
                <span class="batch-item-name">${qr.name}</span>
                <button class="btn-secondary" onclick="app.downloadBatchItem('${qr.name}', '${qr.qrcode}')" style="padding: 6px 10px; width: auto; font-size: 12px;">下载</button>
            `;
            grid.appendChild(item);
        });

        resultsDiv.style.display = 'block';
    }

    downloadBatchItem(name, image) {
        const link = document.createElement('a');
        link.href = image;
        link.download = `${name}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    downloadBatchAll() {
        this.batchQrcodes.forEach((qr, index) => {
            setTimeout(() => {
                this.downloadBatchItem(qr.name, qr.qrcode);
            }, index * 200);
        });
        this.showNotification('开始下载...', 'success');
    }

    addToHistory(content, image) {
        this.history.unshift({
            content: typeof content === 'string' ? content : JSON.stringify(content),
            image: image,
            timestamp: new Date().toLocaleString()
        });

        if (this.history.length > 50) {
            this.history.pop();
        }

        localStorage.setItem('qrcode_history', JSON.stringify(this.history));
        this.loadHistory();
    }

    loadHistory() {
        const saved = localStorage.getItem('qrcode_history');
        this.history = saved ? JSON.parse(saved) : [];
        this.displayHistory();
    }

    displayHistory() {
        const historyList = document.getElementById('history-list');
        
        if (this.history.length === 0) {
            historyList.innerHTML = '<p style="text-align: center; color: #999;">暂无历史记录</p>';
            return;
        }

        historyList.innerHTML = this.history.map((item, index) => `
            <div class="history-item" onclick="app.restoreFromHistory(${index})">
                <div class="history-thumb">
                    <img src="${item.image}" alt="历史二维码">
                </div>
                <div class="history-info">
                    <div class="history-content">${item.content.substring(0, 50)}${item.content.length > 50 ? '...' : ''}</div>
                    <div class="history-time">${item.timestamp}</div>
                </div>
                <button class="history-delete-btn" onclick="event.stopPropagation(); app.deleteHistoryItem(${index})" title="删除">×</button>
            </div>
        `).join('');
    }

    deleteHistoryItem(index) {
        this.history.splice(index, 1);
        localStorage.setItem('qrcode_history', JSON.stringify(this.history));
        this.displayHistory();
        this.showNotification('已删除', 'info');
    }

    restoreFromHistory(index) {
        const item = this.history[index];
        this.currentQrcode = item;
        this.displayQrcode(item.image);
        this.switchTab('generator');
        this.showNotification('已恢复历史记录', 'success');
    }

    async loadTemplates() {
        try {
            const response = await fetch('/api/templates');
            const data = await response.json();
            if (!data.success) { console.warn('模板数据加载失败'); return; }
            this.allTemplates = (data.templates || []).filter(t =>
                t.type === 'text' || t.type === 'questionnaire' || t.type === 'form'
            );
            console.log('模板加载成功，共', this.allTemplates.length, '个模板');
            this.renderTemplates('all', '');
            const grid = document.querySelector('.templates-grid');
            if (grid) {
                grid.addEventListener('click', (e) => {
                    const genBtn = e.target.closest('.tpl-gen-btn');
                    if (genBtn) {
                        e.stopPropagation();
                        this.generateFromCard(genBtn.dataset.type, parseInt(genBtn.dataset.idx));
                        return;
                    }
                    const star = e.target.closest('.tpl-star');
                    if (star) {
                        e.stopPropagation();
                        const group = star.closest('.tpl-star-group');
                        const val = star.dataset.val;
                        const hidden = group.querySelector('input[type=hidden]');
                        if (hidden) hidden.value = val;
                        group.querySelectorAll('.tpl-star').forEach((s, i) => {
                            s.classList.toggle('active', i < parseInt(val));
                        });
                        return;
                    }
                    const card = e.target.closest('.template-card');
                    if (!card) return;
                    if (card.classList.contains('expanded')) return;
                    document.querySelectorAll('.template-card.expanded').forEach(c => c.classList.remove('expanded'));
                    card.classList.add('expanded');
                });
            }
            document.querySelectorAll('.filter-btn').forEach(b => {
                b.addEventListener('click', () => {
                    document.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active-filter'));
                    b.classList.add('active-filter');
                    const keyword = document.getElementById('template-search-input')?.value || '';
                    this.renderTemplates(b.dataset.filter, keyword);
                });
            });
            grid.addEventListener('change', (e) => {
                if (e.target.type === 'file' && e.target.files && e.target.files.length > 0) {
                    const pfx = e.target.id.replace(/file$/, '');
                    const info = document.getElementById(pfx + 'file-info');
                    if (info) {
                        info.style.display = 'block';
                        info.textContent = '附件: ' + e.target.files[0].name + ' (' + (e.target.files[0].size / 1024).toFixed(1) + ' KB)';
                    }
                }
            });
        } catch (error) {
            console.error('加载模板失败:', error);
            const grid = document.querySelector('.templates-grid');
            if (grid) grid.innerHTML = '<div style="text-align:center;padding:40px;color:#e74c3c;">模板加载失败，请刷新页面重试</div>';
        }
    }

    renderTemplates(filter, keyword) {
        const grid = document.querySelector('.templates-grid');
        if (!grid) return;
        if (!this.allTemplates || !Array.isArray(this.allTemplates)) {
            grid.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">模板加载中...</div>';
            return;
        }
        let list = filter === 'all' ? this.allTemplates : this.allTemplates.filter(t => t.type === filter);
        if (keyword) {
            const kw = keyword.toLowerCase();
            list = list.filter(t => t.name.toLowerCase().includes(kw) || (t.description || '').toLowerCase().includes(kw) || t.type.toLowerCase().includes(kw));
        }
        if (list.length === 0) {
            grid.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">没有找到匹配的模板</div>';
            return;
        }
        grid.innerHTML = list.map((t, idx) => {
            const raw = (t.content || '').replace(/\\n/g, '\n');
            const bodyHtml = this.buildTemplateFields(t.type, raw, idx);
            return '<div class="template-card" data-type="' + t.type + '" data-idx="' + idx + '">' +
                '<div class="template-card-header">' +
                    '<span class="template-icon">' + this.getTemplateIcon(t.type) + '</span>' +
                    '<div>' +
                        '<div class="template-name">' + t.name + '</div>' +
                        '<div class="template-desc">' + (t.description || '') + '</div>' +
                    '</div>' +
                '</div>' +
                '<div class="template-card-body">' + bodyHtml + '</div>' +
            '</div>';
        }).join('');
    }

    buildTemplateFields(type, raw, idx) {
        const pfx = 'tpl-' + idx + '-';
        let h = '';
        if (type === 'vcard') {
            const m = raw.match(/FN:([^\n]*)/); const t = raw.match(/TEL:([^\n]*)/); const e = raw.match(/EMAIL:([^\n]*)/); const o = raw.match(/ORG:([^\n]*)/); const ti = raw.match(/TITLE:([^\n]*)/);
            h = this.fg(pfx+'name','姓名',m?m[1]:'','text') + this.fg(pfx+'title','职位',ti?ti[1]:'','text') + this.fg(pfx+'phone','电话',t?t[1]:'','tel') + this.fg(pfx+'email','邮箱',e?e[1]:'','email') + this.fg(pfx+'company','公司',o?o[1]:'','text');
        } else if (type === 'wifi') {
            const s = raw.match(/S:([^;]*)/); const p = raw.match(/P:([^;]*)/); const sec = raw.match(/T:([^;]*)/);
            const sv = sec ? (sec[1]==='WPA2'?'WPA2':sec[1]==='WEP'?'WEP':sec[1]==='nopass'?'nopass':'WPA') : 'WPA';
            h = this.fg(pfx+'ssid','网络名称',s?s[1]:'','text') + this.fg(pfx+'password','密码',p?p[1]:'','password') +
                '<div class="form-group"><label>加密方式</label><select id="' + pfx + 'security" class="select-field">' +
                '<option value="WPA"' + (sv==='WPA'?' selected':'') + '>WPA</option>' +
                '<option value="WPA2"' + (sv==='WPA2'?' selected':'') + '>WPA2</option>' +
                '<option value="WEP"' + (sv==='WEP'?' selected':'') + '>WEP</option>' +
                '<option value="nopass"' + (sv==='nopass'?' selected':'') + '>无密码</option></select></div>';
        } else if (type === 'email') {
            const to = raw.match(/mailto:([^?]*)/); const subj = raw.match(/subject=([^&]*)/); const bd = raw.match(/body=(.*)/);
            h = this.fg(pfx+'to','邮箱地址',to?decodeURIComponent(to[1]):'','email') + this.fg(pfx+'subject','主题',subj?decodeURIComponent(subj[1]):'','text') +
                '<div class="form-group"><label>正文</label><textarea id="' + pfx + 'body" class="input-field" rows="3">' + (bd?decodeURIComponent(bd[1]):'') + '</textarea></div>';
        } else if (type === 'url') {
            h = this.fg(pfx+'url','网址',raw,'url');
        } else if (type === 'questionnaire' || type === 'form' || type === 'text') {
            h = this.buildLabeledFields(raw, pfx);
        } else if (type === 'file' || type === 'image' || type === 'media') {
            h = '<div class="form-group"><label>上传文件</label>' +
                '<div style="border:2px dashed #dde1e6;border-radius:8px;padding:16px;text-align:center;cursor:pointer;position:relative" class="tpl-upload-zone" data-pfx="' + pfx + '">' +
                '<div style="font-size:24px;margin-bottom:4px">+</div>' +
                '<div style="font-size:12px;color:#888">点击选择文件或拖拽到此处</div>' +
                '<input type="file" id="' + pfx + 'file" style="position:absolute;inset:0;opacity:0;cursor:pointer" accept="' + (type==='image'?'image/*':type==='media'?'audio/*,video/*':'*/*') + '">' +
                '</div>' +
                '<div id="' + pfx + 'file-info" style="font-size:12px;color:#666;margin-top:6px;display:none"></div></div>' +
                '<div class="form-group"><label>内容描述</label><textarea id="' + pfx + 'content" class="input-field" rows="2">' + this.esc(raw) + '</textarea></div>';
        } else {
            h = '<div class="form-group"><label>内容</label><textarea id="' + pfx + 'content" class="input-field" rows="4">' + this.esc(raw) + '</textarea></div>';
        }
        h += '<button class="tpl-gen-btn" data-type="' + type + '" data-idx="' + idx + '">生成二维码</button>';
        h += '<div class="tpl-qr-result" id="' + pfx + 'qr-result"></div>';
        return h;
    }

    buildLabeledFields(raw, pfx) {
        const lines = raw.split('\n');
        let h = '';
        let fieldIdx = 0;
        for (const line of lines) {
            const m = line.match(/^【(.+?)】(.*)$/);
            if (!m) { if (line.trim()) h += '<div style="font-size:12px;color:#888;margin:4px 0">' + this.esc(line) + '</div>'; continue; }
            const label = m[1];
            const rest = m[2];
            const fid = pfx + 'f' + fieldIdx++;
            const radioMatch = rest.match(/（用户可自定义选项：(.+?)）/);
            const checkMatch = rest.match(/（用户可自定义选项：(.+?)）/);
            const customMatch = rest.match(/（用户可自定义：(.+?)）/);
            const fillMatch = rest.match(/（用户可自定义：___）/);
            const optionsRadio = rest.match(/[○◉]\s*([^○◉☐☑（]+)/g);
            const optionsCheck = rest.match(/[☐☑]\s*([^○◉☐☑（]+)/g);
            const defaultVal = rest.replace(/（[^）]*）/g, '').replace(/（用户可自定义：___）/g, '').trim();
            if (optionsRadio && optionsRadio.length > 1) {
                h += '<div class="form-group"><label>' + this.esc(label) + '</label><div class="tpl-radio-group">';
                optionsRadio.forEach((opt, oi) => {
                    const val = opt.replace(/^[○◉]\s*/, '').trim();
                    h += '<label class="tpl-radio-label"><input type="radio" name="' + fid + '" value="' + this.esc(val) + '"' + (oi === 0 ? ' checked' : '') + '> ' + this.esc(val) + '</label>';
                });
                h += '</div></div>';
            } else if (optionsCheck && optionsCheck.length > 1) {
                h += '<div class="form-group"><label>' + this.esc(label) + '</label><div class="tpl-check-group">';
                optionsCheck.forEach(opt => {
                    const val = opt.replace(/^[☐☑]\s*/, '').trim();
                    h += '<label class="tpl-check-label"><input type="checkbox" name="' + fid + '" value="' + this.esc(val) + '"> ' + this.esc(val) + '</label>';
                });
                h += '</div></div>';
            } else if (fillMatch || rest.includes('___')) {
                const placeholder = defaultVal || '请输入' + label;
                h += this.fg(fid, label, defaultVal, 'text');
            } else if (rest.includes('⭐')) {
                h += '<div class="form-group"><label>' + this.esc(label) + '</label><div class="tpl-star-group" data-fid="' + fid + '">';
                for (let s = 1; s <= 5; s++) h += '<span class="tpl-star" data-val="' + s + '">⭐</span>';
                h += '<input type="hidden" id="' + fid + '" value="5"></div></div>';
            } else {
                const placeholder = defaultVal || '请输入' + label;
                if (defaultVal.length > 30) {
                    h += '<div class="form-group"><label>' + this.esc(label) + '</label><textarea id="' + fid + '" class="input-field" rows="2" placeholder="' + this.esc(placeholder) + '">' + this.esc(defaultVal) + '</textarea></div>';
                } else {
                    h += this.fg(fid, label, defaultVal, 'text');
                }
            }
        }
        return h;
    }

    collectLabeledFields(pfx, raw) {
        const lines = raw.split('\n');
        let result = '';
        let fieldIdx = 0;
        for (const line of lines) {
            const m = line.match(/^【(.+?)】(.*)$/);
            if (!m) { if (line.trim()) result += line + '\n'; continue; }
            const label = m[1];
            const rest = m[2];
            const fid = pfx + 'f' + fieldIdx++;
            const optionsRadio = rest.match(/[○◉]\s*([^○◉☐☑（]+)/g);
            const optionsCheck = rest.match(/[☐☑]\s*([^○◉☐☑（]+)/g);
            const fillMatch = rest.match(/（用户可自定义：___）/);
            if (optionsRadio && optionsRadio.length > 1) {
                const checked = document.querySelector('input[name="' + fid + '"]:checked');
                result += '【' + label + '】' + (checked ? checked.value : optionsRadio[0].replace(/^[○◉]\s*/, '').trim()) + '\n';
            } else if (optionsCheck && optionsCheck.length > 1) {
                const checks = document.querySelectorAll('input[name="' + fid + '"]:checked');
                const vals = Array.from(checks).map(c => c.value);
                result += '【' + label + '】' + (vals.length ? vals.join('、') : '未选择') + '\n';
            } else if (rest.includes('⭐')) {
                const inp = document.getElementById(fid);
                result += '【' + label + '】' + (inp ? inp.value : '5') + '星\n';
            } else {
                const inp = document.getElementById(fid);
                result += '【' + label + '】' + (inp ? inp.value : '') + '\n';
            }
        }
        return result.trim();
    }

    fg(id, label, val, inputType) {
        if (inputType === 'textarea') {
            return '<div class="form-group"><label>' + label + '</label><textarea id="' + id + '" class="input-field" rows="3">' + this.esc(val) + '</textarea></div>';
        }
        return '<div class="form-group"><label>' + label + '</label><input type="' + inputType + '" id="' + id + '" class="input-field" value="' + this.esc(val) + '"></div>';
    }

    esc(s) {
        return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    async generateFromCard(type, idx) {
        const pfx = 'tpl-' + idx + '-';
        const tpl = this.allTemplates[idx];
        const raw = tpl ? tpl.content : '';
        let content;
        if (type === 'vcard') {
            const n = document.getElementById(pfx+'name')?.value||'';
            const ti = document.getElementById(pfx+'title')?.value||'';
            const p = document.getElementById(pfx+'phone')?.value||'';
            const e = document.getElementById(pfx+'email')?.value||'';
            const c = document.getElementById(pfx+'company')?.value||'';
            if (!n&&!p) { this.showNotification('请填写姓名或电话','error'); return; }
            content = 'BEGIN:VCARD\nVERSION:3.0\nFN:'+n+'\nTITLE:'+ti+'\nTEL:'+p+'\nEMAIL:'+e+'\nORG:'+c+'\nEND:VCARD';
        } else if (type === 'wifi') {
            const s = document.getElementById(pfx+'ssid')?.value||'';
            const p = document.getElementById(pfx+'password')?.value||'';
            const sec = document.getElementById(pfx+'security')?.value||'WPA';
            if (!s) { this.showNotification('请填写网络名称','error'); return; }
            content = 'WIFI:T:'+sec+';S:'+s+';P:'+p+';;';
        } else if (type === 'email') {
            const to = document.getElementById(pfx+'to')?.value||'';
            const subj = document.getElementById(pfx+'subject')?.value||'';
            const bd = document.getElementById(pfx+'body')?.value||'';
            if (!to) { this.showNotification('请填写邮箱地址','error'); return; }
            content = 'mailto:'+encodeURIComponent(to)+'?subject='+encodeURIComponent(subj)+'&body='+encodeURIComponent(bd);
        } else if (type === 'url') {
            content = document.getElementById(pfx+'url')?.value||'';
            if (!content) { this.showNotification('请填写网址','error'); return; }
        } else if (type === 'file' || type === 'image' || type === 'media') {
            const fileInput = document.getElementById(pfx+'file');
            if (fileInput && fileInput.files && fileInput.files.length > 0) {
                this.showNotification('上传文件中...','info');
                const formData = new FormData();
                formData.append('file', fileInput.files[0]);
                try {
                    const upRes = await fetch('/api/upload', { method: 'POST', body: formData });
                    const upData = await upRes.json();
                    if (!upData.success) { this.showNotification(upData.error||this.t('toast.uploadFailed','上传失败'),'error'); return; }
                    content = upData.url;
                } catch (err) { this.showNotification(this.t('toast.uploadFailed','上传失败'),'error'); return; }
            } else {
                content = document.getElementById(pfx+'content')?.value||'';
                if (!content.trim()) { this.showNotification('请上传文件或填写描述','error'); return; }
            }
        } else if (type === 'text' || type === 'questionnaire' || type === 'form') {
            content = this.collectLabeledFields(pfx, raw);
            if (!content.trim()) { this.showNotification('请填写内容','error'); return; }
        } else {
            content = document.getElementById(pfx+'content')?.value||'';
            if (!content.trim()) { this.showNotification('请输入内容','error'); return; }
        }
        this.showNotification('生成中...','info');
        await this._doGenerate(content, type, (data) => {
            const qrDiv = document.getElementById(pfx+'qr-result');
            if (qrDiv) {
                qrDiv.innerHTML = '<img src="'+data.qrcode+'" alt="二维码" style="max-width:140px">' +
                    '<div style="margin-top:6px;display:flex;gap:6px;justify-content:center">' +
                    '<button class="btn-secondary" style="font-size:11px;padding:4px 8px" onclick="window.qrApp.downloadQrcode(\'png\')">下载PNG</button>' +
                    '<button class="btn-secondary" style="font-size:11px;padding:4px 8px" onclick="window.qrApp.copyQrcode()">复制</button></div>';
            }
        });
    }

    async _doGenerate(content, type, onSuccess) {
        try {
            const response = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content, type, config: this.getConfig() })
            });
            const data = await response.json();
            if (data.success) {
                this.currentQrcode = { content, type, image: data.qrcode, timestamp: data.timestamp };
                onSuccess(data);
                this.showNotification('生成成功！','success');
            } else {
                this.showNotification(data.error||this.t('toast.generateFailed','生成失败'),'error');
            }
        } catch (e) {
            this.showNotification(this.t('toast.generateFailed','生成失败'),'error');
        }
    }

    searchTemplates(keyword) {
        const activeBtn = document.querySelector('.filter-btn.active-filter');
        const filter = activeBtn ? activeBtn.dataset.filter : 'all';
        this.renderTemplates(filter, keyword);
    }

    getTemplateIcon(type) {
        const icons = { file: '', image: '', media: '', text: '', url: '', vcard: '', wifi: '', email: '', questionnaire: '', form: '' };
        return icons[type] || '';
    }

    useTemplate(type, content) {
        this.currentType = type;
        if (this.currentType === 'url') this.urlSubType = 'static';
        this.showTemplateModal(type, content);
    }

    showTemplateModal(type, content) {
        const modal = document.getElementById('modal');
        const body = document.getElementById('modal-body');
        if (!modal || !body) { console.error('modal或modal-body元素不存在'); return; }
        const rawContent = content ? content.replace(/\\n/g, '\n').replace(/\\'/g, "'") : '';
        console.log('showTemplateModal:', type, rawContent.substring(0, 80));
        const icon = this.getTemplateIcon(type);
        let fieldsHtml = '';
        if (type === 'vcard') {
            const m = rawContent.match(/FN:([^\n]*)/);
            const t = rawContent.match(/TEL:([^\n]*)/);
            const e = rawContent.match(/EMAIL:([^\n]*)/);
            const o = rawContent.match(/ORG:([^\n]*)/);
            const ti = rawContent.match(/TITLE:([^\n]*)/);
            fieldsHtml = '<div class="form-group"><label>姓名</label><input type="text" id="mod-vcard-name" class="input-field" value="' + (m ? m[1] : '') + '"></div>' +
                '<div class="form-group"><label>职位</label><input type="text" id="mod-vcard-title" class="input-field" value="' + (ti ? ti[1] : '') + '"></div>' +
                '<div class="form-group"><label>电话</label><input type="tel" id="mod-vcard-phone" class="input-field" value="' + (t ? t[1] : '') + '"></div>' +
                '<div class="form-group"><label>邮箱</label><input type="email" id="mod-vcard-email" class="input-field" value="' + (e ? e[1] : '') + '"></div>' +
                '<div class="form-group"><label>公司</label><input type="text" id="mod-vcard-company" class="input-field" value="' + (o ? o[1] : '') + '"></div>';
        } else if (type === 'wifi') {
            const s = rawContent.match(/S:([^;]*)/);
            const p = rawContent.match(/P:([^;]*)/);
            const sec = rawContent.match(/T:([^;]*)/);
            const secVal = sec ? (sec[1] === 'WPA' || sec[1] === 'WPA2' ? sec[1] : (sec[1] === 'WEP' ? 'WEP' : 'nopass')) : 'WPA';
            fieldsHtml = '<div class="form-group"><label>网络名称</label><input type="text" id="mod-wifi-ssid" class="input-field" value="' + (s ? s[1] : '') + '"></div>' +
                '<div class="form-group"><label>密码</label><input type="password" id="mod-wifi-password" class="input-field" value="' + (p ? p[1] : '') + '"></div>' +
                '<div class="form-group"><label>加密方式</label><select id="mod-wifi-security" class="select-field">' +
                '<option value="WPA"' + (secVal==='WPA'?' selected':'') + '>WPA</option>' +
                '<option value="WPA2"' + (secVal==='WPA2'?' selected':'') + '>WPA2</option>' +
                '<option value="WEP"' + (secVal==='WEP'?' selected':'') + '>WEP</option>' +
                '<option value="nopass"' + (secVal==='nopass'?' selected':'') + '>无密码</option></select></div>';
        } else if (type === 'email') {
            const to = rawContent.match(/mailto:([^?]*)/);
            const subj = rawContent.match(/subject=([^&]*)/);
            const bd = rawContent.match(/body=(.*)/);
            fieldsHtml = '<div class="form-group"><label>邮箱地址</label><input type="email" id="mod-email-to" class="input-field" value="' + (to ? decodeURIComponent(to[1]) : '') + '"></div>' +
                '<div class="form-group"><label>主题</label><input type="text" id="mod-email-subject" class="input-field" value="' + (subj ? decodeURIComponent(subj[1]) : '') + '"></div>' +
                '<div class="form-group"><label>正文</label><textarea id="mod-email-body" class="input-field" rows="3">' + (bd ? decodeURIComponent(bd[1]) : '') + '</textarea></div>';
        } else if (type === 'url') {
            fieldsHtml = '<div class="form-group"><label>网址</label><input type="url" id="mod-url-input" class="input-field" value="' + rawContent + '"></div>';
        } else if (type === 'questionnaire' || type === 'form') {
            fieldsHtml = '<textarea id="mod-content-input" class="input-field" style="min-height:200px;width:100%" rows="6">' + rawContent + '</textarea>' +
                '<button class="btn-outline" id="mod-form-editor-btn" style="margin-top:8px;width:100%;padding:8px;border:1px dashed #38BDF8;border-radius:6px;background:transparent;color:#38BDF8;cursor:pointer;font-weight:600">高级编辑 — 可视化构建表单</button>';
        } else if (type === 'file' || type === 'image' || type === 'media') {
            fieldsHtml = '<div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px;font-size:13px;color:var(--text-secondary);line-height:1.6">' + rawContent + '</div>' +
                '<div class="form-group"><label>内容描述</label><textarea id="mod-content-input" class="input-field" rows="3">' + rawContent + '</textarea></div>' +
                '<p style="font-size:12px;color:#94a3b8;margin-top:4px">提示：文件/图片/视频类型需在生成器页上传实际文件，此处可编辑描述文本</p>';
        } else {
            fieldsHtml = '<textarea id="mod-content-input" class="input-field" style="min-height:200px;width:100%" rows="8">' + rawContent + '</textarea>';
        }
        const qrArea = '<div id="modal-qr-area" style="display:none;margin-top:16px;text-align:center;border-top:1px solid var(--border);padding-top:16px">' +
            '<div id="modal-qr-preview" style="display:inline-block"></div>' +
            '<div style="margin-top:10px;display:flex;gap:8px;justify-content:center">' +
            '<button class="btn-secondary" id="modal-dl-png" style="font-size:12px;padding:6px 12px">下载PNG</button>' +
            '<button class="btn-secondary" id="modal-dl-svg" style="font-size:12px;padding:6px 12px">下载SVG</button>' +
            '<button class="btn-secondary" id="modal-copy" style="font-size:12px;padding:6px 12px">复制</button></div></div>';
        body.innerHTML = '<h3 style="margin-bottom:16px">' + icon + ' 编辑模板内容</h3>' + fieldsHtml +
            '<div style="margin-top:12px;display:flex;gap:10px;justify-content:flex-end">' +
            '<button class="btn-secondary" onclick="document.getElementById(\'modal\').classList.remove(\'active\')">取消</button>' +
            '<button class="btn-primary" id="modal-gen-btn">生成二维码</button></div>' + qrArea;
        modal.classList.add('active');
        document.getElementById('modal-gen-btn').onclick = () => this.generateFromModal(type);
        const feBtn = document.getElementById('mod-form-editor-btn');
        if (feBtn) {
            feBtn.onclick = () => this.openFormEditorFromModal(type);
        }
    }

    async generateFromModal(type) {
        let content;
        if (type === 'vcard') {
            const n = document.getElementById('mod-vcard-name')?.value || '';
            const p = document.getElementById('mod-vcard-phone')?.value || '';
            const e = document.getElementById('mod-vcard-email')?.value || '';
            const c = document.getElementById('mod-vcard-company')?.value || '';
            const ti = document.getElementById('mod-vcard-title')?.value || '';
            if (!n && !p) { this.showNotification('请填写姓名或电话', 'error'); return; }
            content = 'BEGIN:VCARD\nVERSION:3.0\nFN:' + n + '\nTITLE:' + ti + '\nTEL:' + p + '\nEMAIL:' + e + '\nORG:' + c + '\nEND:VCARD';
        } else if (type === 'wifi') {
            const s = document.getElementById('mod-wifi-ssid')?.value || '';
            const p = document.getElementById('mod-wifi-password')?.value || '';
            const sec = document.getElementById('mod-wifi-security')?.value || 'WPA';
            if (!s) { this.showNotification('请填写网络名称', 'error'); return; }
            content = 'WIFI:T:' + sec + ';S:' + s + ';P:' + p + ';;';
        } else if (type === 'email') {
            const to = document.getElementById('mod-email-to')?.value || '';
            const subj = document.getElementById('mod-email-subject')?.value || '';
            const bd = document.getElementById('mod-email-body')?.value || '';
            if (!to) { this.showNotification('请填写邮箱地址', 'error'); return; }
            content = 'mailto:' + encodeURIComponent(to) + '?subject=' + encodeURIComponent(subj) + '&body=' + encodeURIComponent(bd);
        } else if (type === 'url') {
            content = document.getElementById('mod-url-input')?.value || '';
            if (!content) { this.showNotification('请填写网址', 'error'); return; }
        } else {
            content = document.getElementById('mod-content-input')?.value || '';
            if (!content.trim()) { this.showNotification('请输入内容', 'error'); return; }
        }
        this.showNotification('生成中...', 'info');
        await this._doGenerate(content, type, (data) => {
            const qrArea = document.getElementById('modal-qr-area');
            const qrPreview = document.getElementById('modal-qr-preview');
            if (qrArea && qrPreview) {
                qrArea.style.display = 'block';
                qrPreview.innerHTML = '<img src="' + data.qrcode + '" alt="二维码" style="max-width:200px">';
            }
            document.getElementById('modal-dl-png').onclick = () => this.downloadQrcode('png');
            document.getElementById('modal-dl-svg').onclick = () => this.downloadQrcode('svg');
            document.getElementById('modal-copy').onclick = () => this.copyQrcode();
        });
    }

    openFormEditorFromModal(type) {
        this.currentType = type;
        this.updateInputContainer();
        const textarea = document.getElementById('content-input');
        const modTextarea = document.getElementById('mod-content-input');
        if (textarea && modTextarea) {
            textarea.value = modTextarea.value;
        }
        const origClose = this.closeFormEditor.bind(this);
        this.closeFormEditor = () => {
            origClose();
            this.closeFormEditor = origClose;
            const updatedTextarea = document.getElementById('content-input');
            if (modTextarea && updatedTextarea) {
                modTextarea.value = updatedTextarea.value;
            }
            const schema = document.getElementById('form-schema-json');
            if (schema) schema.value = '';
            this.currentType = null;
        };
        this.openFormEditor();
    }

    setupDragDrop() {
        const fileUploadArea = document.querySelector('.file-upload-area');
        if (!fileUploadArea) return;

        fileUploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            fileUploadArea.style.borderColor = '#38BDF8';
            fileUploadArea.style.backgroundColor = 'rgba(56, 189, 248, 0.05)';
        });

        fileUploadArea.addEventListener('dragleave', () => {
            fileUploadArea.style.borderColor = '#1E293B';
            fileUploadArea.style.backgroundColor = 'var(--bg-secondary)';
        });

        fileUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            fileUploadArea.style.borderColor = '#1E293B';
            fileUploadArea.style.backgroundColor = 'var(--bg-secondary)';

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                document.getElementById('batch-file').files = files;
                const event = new Event('change', { bubbles: true });
                document.getElementById('batch-file').dispatchEvent(event);
            }
        });

        fileUploadArea.addEventListener('click', () => {
            document.getElementById('batch-file').click();
        });
    }

    closeModal() {
        document.getElementById('modal').classList.remove('active');
    }

    showNotification(message, type = 'info', params = {}) {
        const translated = i18n.t(message, params);
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = translated;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    toggleFormEditor() {
        const modal = document.getElementById('form-editor-modal');
        if (modal.classList.contains('active')) {
            this.closeFormEditor();
        } else {
            this.openFormEditor();
        }
    }

    openFormEditor() {
        const modal = document.getElementById('form-editor-modal');
        this.formFields = this.formFields || [];
        modal.classList.add('active');
        this.initFormEditor();
        this.renderFormCanvas();
    }

    closeFormEditor() {
        const modal = document.getElementById('form-editor-modal');
        modal.classList.remove('active');
    }

    initFormEditor() {
        if (this._feInitialized) return;
        this._feInitialized = true;
        const comps = document.querySelectorAll('.fe-comp');
        comps.forEach(comp => {
            comp.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', comp.dataset.type);
            });
            comp.addEventListener('click', () => {
                this.addFormField(comp.dataset.type);
            });
        });
        const canvas = document.getElementById('fe-canvas');
        canvas.addEventListener('dragover', (e) => e.preventDefault());
        canvas.addEventListener('drop', (e) => {
            e.preventDefault();
            const type = e.dataTransfer.getData('text/plain');
            if (type) this.addFormField(type);
        });
    }

    addFormField(type) {
        const fe = (k) => this.t('formEditor.' + k);
        const defaults = {
            text: { label: fe('fieldText'), placeholder: fe('inputPlaceholder'), required: false },
            textarea: { label: fe('fieldTextarea'), placeholder: fe('inputContentPlaceholder'), required: false },
            number: { label: fe('fieldNumber'), placeholder: fe('inputNumberPlaceholder'), required: false },
            radio: { label: fe('fieldRadio'), options: [fe('newOption'), fe('newOption'), fe('newOption')], required: false },
            checkbox: { label: fe('fieldCheckbox'), options: [fe('newOption'), fe('newOption'), fe('newOption')], required: false },
            date: { label: fe('fieldDate'), placeholder: fe('selectDatePlaceholder'), required: false },
            select: { label: fe('fieldSelect'), options: [fe('newOption'), fe('newOption'), fe('newOption')], required: false },
            upload: { label: fe('fieldUpload'), accept: '*/*', required: false },
            rating: { label: fe('fieldRating'), max: 5, required: false },
            description: { label: fe('fieldDescription'), content: fe('descriptionContentDefault') },
            divider: { label: fe('fieldDivider') }
        };
        const field = {
            id: 'fld_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
            type: type,
            ...defaults[type]
        };
        this.formFields = this.formFields || [];
        this.formFields.push(field);
        this.renderFormCanvas();
        this.selectFormField(field.id);
    }

    selectFormField(id) {
        this.selectedFieldId = id;
        this.renderFormCanvas();
        this.renderProperties();
    }

    removeFormField(id) {
        this.formFields = (this.formFields || []).filter(f => f.id !== id);
        if (this.selectedFieldId === id) this.selectedFieldId = null;
        this.renderFormCanvas();
        this.renderProperties();
    }

    renderFormCanvas() {
        const canvas = document.getElementById('fe-canvas');
        const fields = this.formFields || [];
        if (fields.length === 0) {
            canvas.innerHTML = '<div class="fe-drop-hint" style="text-align:center;color:#999;padding:40px;font-size:14px">拖拽左侧组件到此处</div>';
            return;
        }
        canvas.innerHTML = fields.map(f => {
            const isSelected = f.id === this.selectedFieldId;
            const border = isSelected ? '2px solid #38BDF8' : '1px solid #1E293B';
            const bg = isSelected ? '#141414' : '#0F0F0F';
            let preview = '';
            switch (f.type) {
                case 'text': preview = `<input class="fe-preview-input" placeholder="${f.placeholder || ''}" disabled>`; break;
                case 'textarea': preview = `<textarea class="fe-preview-input" placeholder="${f.placeholder || ''}" disabled rows="2"></textarea>`; break;
                case 'number': preview = `<input type="number" class="fe-preview-input" placeholder="${f.placeholder || ''}" disabled>`; break;
                case 'radio': preview = (f.options || []).map((o, i) => `<label style="margin-right:12px;font-size:13px"><input type="radio" disabled ${i === 0 ? 'checked' : ''}> ${o}</label>`).join(''); break;
                case 'checkbox': preview = (f.options || []).map(o => `<label style="margin-right:12px;font-size:13px"><input type="checkbox" disabled> ${o}</label>`).join(''); break;
                case 'date': preview = `<input type="date" class="fe-preview-input" disabled>`; break;
                case 'select': preview = `<select class="fe-preview-input" disabled><option>${(f.options || [this.t('formEditor.pleaseSelect')])[0]}</option></select>`; break;
                case 'upload': preview = `<div style="border:1px dashed #ccc;padding:12px;text-align:center;color:#999;font-size:12px;border-radius:4px">${this.t('formEditor.clickUpload')}</div>`; break;
                case 'rating': preview = '⭐'.repeat(f.max || 5).split('').map((s, i) => `<span style="color:#${i < (f.max || 5) ? 'f5a623' : 'ddd'};font-size:18px">${s}</span>`).join(''); break;
                case 'description': preview = `<div style="color:#666;font-size:13px;line-height:1.6">${f.content || ''}</div>`; break;
                case 'divider': preview = `<hr style="border:none;border-top:1px solid #1E293B">`; break;
            }
            return `<div class="fe-canvas-field" data-id="${f.id}" style="border:${border};background:${bg};border-radius:6px;padding:12px;margin-bottom:10px;cursor:pointer;position:relative" onclick="window.qrApp.selectFormField('${f.id}')">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                    <span style="font-size:13px;font-weight:600">${f.label || ''}${f.required ? ' <span style="color:red">*</span>' : ''}</span>
                    <div style="display:flex;gap:4px">
                        <button onclick="event.stopPropagation();window.qrApp.moveFormField('${f.id}',-1)" style="background:none;border:none;cursor:pointer;font-size:12px;padding:2px 4px">⬆</button>
                        <button onclick="event.stopPropagation();window.qrApp.moveFormField('${f.id}',1)" style="background:none;border:none;cursor:pointer;font-size:12px;padding:2px 4px">⬇</button>
                        <button onclick="event.stopPropagation();window.qrApp.removeFormField('${f.id}')" style="background:none;border:none;cursor:pointer;font-size:12px;color:#e74c3c;padding:2px 4px">✕</button>
                    </div>
                </div>
                <div>${preview}</div>
                <div style="font-size:10px;color:#999;margin-top:4px">${f.type} | ${f.id}</div>
            </div>`;
        }).join('');
        this.initSortable();
    }

    moveFormField(id, direction) {
        const idx = (this.formFields || []).findIndex(f => f.id === id);
        if (idx < 0) return;
        const newIdx = idx + direction;
        if (newIdx < 0 || newIdx >= this.formFields.length) return;
        [this.formFields[idx], this.formFields[newIdx]] = [this.formFields[newIdx], this.formFields[idx]];
        this.renderFormCanvas();
    }

    renderProperties() {
        const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
        const container = document.getElementById('fe-props-content');
        const fe = (k) => this.t('formEditor.' + k);
        const field = (this.formFields || []).find(f => f.id === this.selectedFieldId);
        if (!field) {
            container.innerHTML = `<div style="font-size:13px;color:#999">${fe('selectField')}</div>`;
            return;
        }
        let optEditor = '';
        if (['radio', 'checkbox', 'select'].includes(field.type)) {
            optEditor = `<div style="margin-bottom:12px">
                <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">${fe('optionsList')}</label>
                <div id="fe-options-list">${(field.options || []).map((o, i) => `<div style="display:flex;gap:4px;margin-bottom:4px"><input value="${esc(o)}" onchange="window.qrApp.updateFieldOption('${field.id}',${i},this.value)" style="flex:1;padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px"><button onclick="window.qrApp.removeFieldOption('${field.id}',${i})" style="background:none;border:none;color:#e74c3c;cursor:pointer;font-size:12px">✕</button></div>`).join('')}</div>
                <button onclick="window.qrApp.addFieldOption('${field.id}')" style="background:#f0f0f0;border:1px solid #ddd;border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer">+ ${fe('addOption')}</button>
            </div>`;
        }
        let ratingEditor = '';
        if (field.type === 'rating') {
            ratingEditor = `<div style="margin-bottom:12px">
                <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">${fe('maxStars')}</label>
                <input type="number" value="${field.max || 5}" min="1" max="10" onchange="window.qrApp.updateFieldProp('${field.id}','max',parseInt(this.value))" style="width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px">
            </div>`;
        }
        container.innerHTML = `
            <div style="margin-bottom:12px">
                <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">${fe('fieldLabel')}</label>
                <input value="${field.label || ''}" onchange="window.qrApp.updateFieldProp('${field.id}','label',this.value)" style="width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px">
            </div>
            ${field.type !== 'divider' && field.type !== 'description' && field.type !== 'rating' ? `
            <div style="margin-bottom:12px">
                <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">${fe('placeholderText')}</label>
                <input value="${field.placeholder || ''}" onchange="window.qrApp.updateFieldProp('${field.id}','placeholder',this.value)" style="width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px">
            </div>` : ''}
            ${field.type === 'description' ? `
            <div style="margin-bottom:12px">
                <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">${fe('descriptionContent')}</label>
                <textarea onchange="window.qrApp.updateFieldProp('${field.id}','content',this.value)" style="width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px" rows="3">${field.content || ''}</textarea>
            </div>` : ''}
            ${field.type !== 'divider' && field.type !== 'description' ? `
            <div style="margin-bottom:12px;display:flex;align-items:center;justify-content:space-between">
                <label style="font-size:12px;color:#666">${fe('required')}</label>
                <label style="position:relative;display:inline-block;width:40px;height:22px">
                    <input type="checkbox" ${field.required ? 'checked' : ''} onchange="window.qrApp.updateFieldProp('${field.id}','required',this.checked)" style="position:absolute;opacity:0;pointer-events:none">
                    <span style="position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:${field.required ? '#38BDF8' : '#1E293B'};border-radius:22px;transition:0.3s"></span>
                    <span style="position:absolute;content:'';height:16px;width:16px;left:${field.required ? '22px' : '3px'};bottom:3px;background:white;border-radius:50%;transition:0.3s"></span>
                </label>
            </div>` : ''}
            ${optEditor}
            ${ratingEditor}
            <div style="margin-bottom:12px">
                <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">${fe('fieldId')}</label>
                <input value="${field.id}" disabled style="width:100%;padding:6px 8px;border:1px solid #eee;border-radius:4px;font-size:11px;background:#f9f9f9;color:#999">
            </div>
            <button onclick="window.qrApp.removeFormField('${field.id}')" style="width:100%;padding:8px;background:#fff;border:1px solid #e74c3c;color:#e74c3c;border-radius:4px;font-size:12px;cursor:pointer">${fe('deleteField')}</button>
        `;
    }

    updateFieldProp(id, key, value) {
        const field = (this.formFields || []).find(f => f.id === id);
        if (field) { field[key] = value; this.renderFormCanvas(); setTimeout(() => this.renderProperties(), 0); }
    }

    updateFieldOption(fieldId, index, value) {
        const field = (this.formFields || []).find(f => f.id === fieldId);
        if (field && field.options) { field.options[index] = value; this.renderFormCanvas(); setTimeout(() => this.renderProperties(), 0); }
    }

    addFieldOption(fieldId) {
        const field = (this.formFields || []).find(f => f.id === fieldId);
        if (field && field.options) { field.options.push('新选项'); this.renderProperties(); this.renderFormCanvas(); }
    }

    removeFieldOption(fieldId, index) {
        const field = (this.formFields || []).find(f => f.id === fieldId);
        if (field && field.options && field.options.length > 1) { field.options.splice(index, 1); this.renderProperties(); this.renderFormCanvas(); }
    }

    initSortable() {
        const canvas = document.getElementById('fe-canvas');
        if (typeof Sortable === 'undefined') return;
        if (this._sortable) this._sortable.destroy();
        this._sortable = new Sortable(canvas, {
            animation: 150,
            handle: '.fe-canvas-field',
            ghostClass: 'fe-ghost',
            onEnd: () => {
                const ids = Array.from(canvas.querySelectorAll('.fe-canvas-field')).map(el => el.dataset.id);
                const newFields = ids.map(id => this.formFields.find(f => f.id === id)).filter(Boolean);
                this.formFields = newFields;
            }
        });
    }

    exportFormJSON() {
        const schema = {
            formName: '未命名表单',
            fields: this.formFields || [],
            createdAt: new Date().toISOString()
        };
        const json = JSON.stringify(schema, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'form-schema.json';
        a.click();
        URL.revokeObjectURL(url);
        this.showNotification('表单配置已导出', 'success');
    }

    saveFormAndClose() {
        const schema = {
            formName: '问卷表单',
            fields: this.formFields || [],
            createdAt: new Date().toISOString()
        };
        const json = JSON.stringify(schema);
        const hidden = document.getElementById('form-schema-json');
        if (hidden) hidden.value = json;
        const textarea = document.getElementById('content-input');
        if (textarea) {
            const labels = (this.formFields || []).map(f => f.label).join('、');
            textarea.value = `表单问卷（${this.formFields.length}个字段）：${labels}`;
        }
        this.closeFormEditor();
        this.showNotification('表单已保存到问卷内容中', 'success');
    }

    // ============ 工作台方法 ============

    async loadWorkspace() {
        await this.loadWorkspaceLayout();
        if (!this.isAuthenticated) return;

        try {
            const res = await fetch('/api/workspace/summary');
            const data = await res.json();
            if (!data.success) return;

            this.renderWorkspaceGreeting(data.greeting);
            this.renderWorkspacePending(data.pending);
            this.renderWorkspaceTodayStats(data.today_stats);
            this.renderWorkspaceTrend(data.week_trend);
            this.renderWorkspaceResources(data.resource_overview);
            this.renderWorkspaceActivities(data.recent_activities);
        } catch (e) {
            console.error('工作台加载失败:', e);
        }
    }

    renderWorkspaceGreeting(greeting) {
        document.getElementById('ws-greeting-text')
            .textContent = greeting.text;
        document.getElementById('ws-greeting-time')
            .textContent = greeting.time;
        document.getElementById('ws-role-label')
            .textContent = greeting.role_label;
    }

    renderWorkspacePending(pending) {
        const banner = document.getElementById('ws-pending-banner');
        if (pending.total_pending > 0) {
            banner.classList.remove('hidden');
            document.getElementById('ws-pending-text')
                .textContent =
                '你有 ' + pending.total_pending + ' 项待处理事项，请及时跟进';
        }

        const renderCard = (countEl, listEl, count, items, renderItem) => {
            document.getElementById(countEl).textContent = count;
            if (count === 0) {
                document.getElementById(countEl)
                    .classList.add('zero');
            }
            const listDom = document.getElementById(listEl);
            if (items.length === 0) {
                listDom.innerHTML =
                    '<div class="ws-card-list-empty">暂无待处理</div>';
                return;
            }
            listDom.innerHTML = items.slice(0, 4)
                .map(renderItem).join('');
        };

        renderCard(
            'ws-count-inspection',
            'ws-list-inspection',
            pending.overdue_inspections.count,
            pending.overdue_inspections.list,
            item => '<div class="ws-card-list-item"'
                + ' title="' + (item.asset_name || '未绑定资产') + '">'
                + (item.asset_name || '未知资产')
                + '（逾期' + (item.days_overdue || 0) + '天）'
                + '</div>'
        );

        renderCard(
            'ws-count-workorder',
            'ws-list-workorder',
            pending.open_workorders.count,
            pending.open_workorders.list,
            item => {
                const priorityMap = {
                    urgent:'紧急', high:'高',
                    normal:'普通', low:'低'
                };
                return '<div class="ws-card-list-item"'
                    + ' title="' + item.title + '">'
                    + '[' + (priorityMap[item.priority]||'普通') + '] '
                    + item.title
                    + '</div>';
            }
        );

        renderCard(
            'ws-count-approval',
            'ws-list-approval',
            pending.pending_submissions.count,
            pending.pending_submissions.list,
            item => '<div class="ws-card-list-item"'
                + ' title="' + item.form_name + '">'
                + item.form_name
                + '</div>'
        );

        renderCard(
            'ws-count-abnormal',
            'ws-list-abnormal',
            pending.abnormal_qrcodes.count,
            pending.abnormal_qrcodes.list,
            item => {
                const statusMap = {
                    expired:'已过期', exhausted:'次数耗尽',
                    disabled:'已停用'
                };
                return '<div class="ws-card-list-item"'
                    + ' title="' + item.title + '">'
                    + item.title
                    + '（' + (statusMap[item.link_status]||'异常') + '）'
                    + '</div>';
            }
        );
    }

    renderWorkspaceTodayStats(stats) {
        const el = (id) => document.getElementById(id);
        const set = (id, val) => { const e = el(id); if (e) e.textContent = val; };
        set('ws-today-scans', stats.scans.toLocaleString());
        set('ws-today-qrcodes', stats.new_qrcodes);
        set('ws-today-forms', stats.new_forms);
        set('ws-today-workorders', stats.new_workorders);
    }

    renderWorkspaceTrend(weekTrend) {
        const chart = document.getElementById('ws-trend-chart');
        if (!weekTrend || weekTrend.length === 0) {
            chart.innerHTML =
                '<div style="color:var(--text-muted);'+
                'font-size:13px;text-align:center;width:100%">暂无数据</div>';
            return;
        }
        const maxCount = Math.max(...weekTrend.map(d => d.count), 1);
        const today = new Date().toISOString().slice(0, 10);
        chart.innerHTML = weekTrend.map(d => {
            const heightPct = Math.max(
                (d.count / maxCount) * 100, 3);
            const isToday = d.date === today;
            const dateLabel = d.date.slice(5);
            return '<div class="ws-trend-bar-wrap">'
                + '<div class="ws-trend-count">' + d.count + '</div>'
                + '<div class="ws-trend-bar ' + (isToday ? 'today' : '') + '"'
                + ' style="height:' + heightPct + '%"'
                + ' data-count="' + d.count + '"></div>'
                + '<div class="ws-trend-date">'
                + dateLabel + (isToday ? '(今)' : '')
                + '</div>'
                + '</div>';
        }).join('');
    }

    renderWorkspaceResources(overview) {
        document.getElementById('ws-res-qrcodes')
            .textContent = overview.total_qrcodes;
        document.getElementById('ws-res-assets')
            .textContent = overview.total_assets;
        document.getElementById('ws-res-forms')
            .textContent = overview.total_forms;
        document.getElementById('ws-res-files')
            .textContent = overview.total_files;

        const bytes = overview.storage_used || 0;
        let storageText;
        if (bytes < 1024 * 1024) {
            storageText = (bytes / 1024).toFixed(1) + 'KB';
        } else if (bytes < 1024 * 1024 * 1024) {
            storageText = (bytes / 1024 / 1024).toFixed(1) + 'MB';
        } else {
            storageText = (bytes / 1024 / 1024 / 1024).toFixed(2) + 'GB';
        }
        document.getElementById('ws-res-storage')
            .textContent = storageText;
    }

    renderWorkspaceActivities(activities) {
        const actionMap = {
            'create_dynamic_link': '创建了活码',
            'update_dynamic_link': '修改了活码',
            'delete_dynamic_link': '删除了活码',
            'toggle_dynamic_link': '切换了活码状态',
            'create_asset': '创建了资产',
            'update_asset': '更新了资产',
            'create_workorder': '创建了工单',
            'resolve_workorder': '解决了工单',
            'assign_workorder': '分配了工单',
            'submit_inspection': '提交了巡检记录',
            'create_form': '创建了表单',
            'delete_form': '删除了表单',
            'invite_user': '邀请了用户',
            'change_role': '修改了用户角色',
            'archive_qrcode': '归档了二维码',
            'delete_qrcode': '删除了二维码'
        };
        const list =
            document.getElementById('ws-activity-list');
        if (!activities || activities.length === 0) {
            list.innerHTML =
                '<div class="ws-activity-empty">暂无活动记录</div>';
            return;
        }
        list.innerHTML = activities.map(a => {
            const actionText =
                actionMap[a.action] || a.action;
            const timeStr = a.created_at
                ? a.created_at.slice(5, 16).replace('T', ' ')
                : '';
            return '<div class="ws-activity-item">'
                + '<div class="ws-activity-dot"></div>'
                + '<div class="ws-activity-text">'
                + actionText
                + '</div>'
                + '<div class="ws-activity-user">'
                + (a.username || '系统')
                + '</div>'
                + '<div class="ws-activity-time">' + timeStr + '</div>'
                + '</div>';
        }).join('');
    }

    goToSection(section) {
        const navItem = document.querySelector(
            '[data-tab="' + section + '"]');
        if (navItem) navItem.click();
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ============ 二维码生命周期管理 ============

    async loadLifecycleList(statusFilter = '') {
        if (!this.isAuthenticated) return;

        try {
            const url = statusFilter
                ? '/api/qrcodes/lifecycle/list?status=' + encodeURIComponent(statusFilter)
                : '/api/qrcodes/lifecycle/list';
            const res = await fetch(url);
            const data = await res.json();
            if (!data.success) return;

            this.renderLifecycleFilters(data.statuses);
            this.renderLifecycleList(data.qrcodes);
        } catch (e) {
            console.error('生命周期列表加载失败:', e);
        }
    }

    renderLifecycleFilters(statuses) {
        const container = document.querySelector('.lifecycle-status-filter');
        if (!container) return;

        let html = '<button class="lc-filter-btn active" data-filter="all">' + this.t('common.all') + '</button>';
        for (const s of statuses) {
            html += '<button class="lc-filter-btn" data-filter="' + s.key + '">' + s.label + '</button>';
        }
        container.innerHTML = html;

        container.querySelectorAll('.lc-filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.lc-filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const filter = btn.dataset.filter;
                this.loadLifecycleList(filter === 'all' ? '' : filter);
            });
        });
    }

    renderLifecycleList(qrcodes) {
        const container = document.getElementById('lifecycle-list');
        if (!container) return;

        if (qrcodes.length === 0) {
            container.innerHTML = '<div class="lc-empty">' + this.t('lifecycle.none') + '</div>';
            return;
        }

        container.innerHTML = qrcodes.map(qr => {
            const timeStr = (qr.created_at || '').slice(0, 10);
            const scans = qr.scan_count || 0;

            let actionsHtml = '';
            const transitions = qr.available_transitions || [];
            for (const t of transitions) {
                let cls = 'lc-action-btn';
                if (t === 'deleted') cls += ' danger';
                else if (t === 'published' || t === 'running') cls += ' success';
                else if (t === 'reviewing' || t === 'paused' || t === 'expired') cls += ' warning';
                const labelMap = {
                    'reviewing': '提交审核', 'published': '发布', 'running': '恢复运行',
                    'paused': '暂停', 'expired': '标记失效', 'archived': '归档', 'deleted': '删除'
                };
                actionsHtml += '<button class="' + cls + '" onclick="event.stopPropagation();app.transitionLifecycle(' + qr.id + ",'" + t + '\')">' + (labelMap[t] || t) + '</button>';
            }

            return '<div class="lc-item" onclick="app.showTimeline(' + qr.id + ')">'
                + '<span class="lc-item-status" style="background:' + qr.status_color + '22;color:' + qr.status_color + '">' + qr.status_label + '</span>'
                + '<span class="lc-item-title">' + this.escapeHtml(qr.title) + '</span>'
                + '<span class="lc-item-meta">'
                + '<span>' + scans + ' 次扫描</span>'
                + '<span>' + timeStr + '</span>'
                + '</span>'
                + '<div class="lc-item-actions">' + actionsHtml + '</div>'
                + '</div>';
        }).join('');
    }

    async showTimeline(qrcodeId) {
        try {
            const res = await fetch('/api/qrcodes/lifecycle/' + qrcodeId + '/timeline');
            const data = await res.json();
            if (!data.success) return;

            document.getElementById('timeline-title').textContent = data.qrcode.title + ' (' + this.t('lifecycle.title') + ')';
            document.getElementById('lifecycle-list').style.display = 'none';
            document.getElementById('lifecycle-timeline-panel').style.display = '';

            this.renderTimeline(data.timeline, data.qrcode);
        } catch (e) {
            console.error('时间轴加载失败:', e);
        }
    }

    renderTimeline(events, qrcode) {
        const container = document.getElementById('timeline-container');
        if (!container) return;

        const currentStatus = qrcode.status;
        const statusOrder = ['created', 'reviewing', 'published', 'running', 'paused', 'expired', 'archived', 'deleted'];
        const currentIdx = statusOrder.indexOf(currentStatus);

        container.innerHTML = events.map((evt, i) => {
            let dotClass = '';
            const evtIdx = statusOrder.indexOf(evt.stage);
            if (evt.stage === currentStatus) {
                dotClass = 'active';
            } else if (evtIdx !== -1 && evtIdx < currentIdx) {
                dotClass = 'passed';
            }

            const timeStr = evt.timestamp
                ? evt.timestamp.slice(0, 19).replace('T', ' ')
                : '';

            return '<div class="timeline-event">'
                + '<div class="timeline-dot ' + dotClass + '"></div>'
                + '<div class="timeline-event-label">' + evt.label + '</div>'
                + '<div class="timeline-event-time">' + timeStr + '</div>'
                + (evt.detail ? '<div class="timeline-event-detail">' + this.escapeHtml(evt.detail) + '</div>' : '')
                + '<div class="timeline-event-actor">' + this.t('common.user') + ': ' + (evt.actor || this.t('error.system')) + '</div>'
                + '</div>';
        }).join('');

        if (qrcode.available_transitions.length > 0) {
            const labelMap = {
                'reviewing': '提交审核', 'published': '发布', 'running': '恢复运行',
                'paused': '暂停', 'expired': '标记失效', 'archived': '归档', 'deleted': '删除'
            };
            let actionsHtml = '';
            for (const t of qrcode.available_transitions) {
                let cls = 'lc-action-btn';
                if (t === 'deleted') cls += ' danger';
                else if (t === 'published' || t === 'running') cls += ' success';
                else if (t === 'reviewing' || t === 'paused' || t === 'expired') cls += ' warning';
                actionsHtml += '<button class="' + cls + '" onclick="app.transitionLifecycle(' + qrcode.id + ",'" + t + '\')">' + (labelMap[t] || t) + '</button>';
            }
            container.innerHTML += '<div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border);display:flex;gap:8px;">' + actionsHtml + '</div>';
        }
    }

    async transitionLifecycle(qrcodeId, targetStatus) {
        const labelMap = {
            'reviewing': '提交审核', 'published': '发布', 'running': '恢复运行',
            'paused': '暂停', 'expired': '标记失效', 'archived': '归档', 'deleted': '删除'
        };
        const actionLabel = labelMap[targetStatus] || targetStatus;

        if (targetStatus === 'deleted') {
            if (!confirm(this.t('error.confirmDelete'))) return;
        }

        let comment = '';
        if (targetStatus === 'reviewing') {
            comment = prompt('审核备注（可选）:') || '';
        }

        try {
            const res = await fetch('/api/qrcodes/lifecycle/transition', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    qrcode_id: qrcodeId,
                    target_status: targetStatus,
                    comment: comment
                })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message || this.t('toast.operationSuccess', '操作成功'), 'success');
                const panel = document.getElementById('lifecycle-timeline-panel');
                if (panel && panel.style.display !== 'none') {
                    this.showTimeline(qrcodeId);
                }
                this.loadLifecycleList();
            } else {
                this.showNotification(data.error || this.t('toast.operationFailed', '操作失败'), 'error');
            }
        } catch (e) {
            console.error('状态流转失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    // ============ 审计日志 ============

    async loadAuditLogs(page = 1) {
        if (!this.isAuthenticated) return;

        try {
            const params = new URLSearchParams();
            params.set('page', page);
            params.set('size', '20');

            const keyword = document.getElementById('audit-keyword')?.value.trim();
            const resourceType = document.getElementById('audit-resource-type')?.value;
            const action = document.getElementById('audit-action')?.value;
            const userId = document.getElementById('audit-user')?.value;
            const startDate = document.getElementById('audit-start-date')?.value;
            const endDate = document.getElementById('audit-end-date')?.value;

            if (keyword) params.set('keyword', keyword);
            if (resourceType) params.set('resource_type', resourceType);
            if (action) params.set('action', action);
            if (userId) params.set('user_id', userId);
            if (startDate) params.set('start_date', startDate);
            if (endDate) params.set('end_date', endDate);

            const res = await fetch('/api/audit?' + params.toString());
            const data = await res.json();
            if (!data.success) return;

            this.renderAuditTable(data.logs);
            this.renderAuditPagination(data.page, data.total_pages, data.total);
            this.renderAuditStats(data.total);
        } catch (e) {
            console.error('审计日志加载失败:', e);
        }
    }

    searchAudit() {
        this.loadAuditLogs(1);
    }

    resetAuditFilters() {
        const keyword = document.getElementById('audit-keyword');
        const resourceType = document.getElementById('audit-resource-type');
        const action = document.getElementById('audit-action');
        const user = document.getElementById('audit-user');
        const startDate = document.getElementById('audit-start-date');
        const endDate = document.getElementById('audit-end-date');
        if (keyword) keyword.value = '';
        if (resourceType) resourceType.value = '';
        if (action) action.value = '';
        if (user) user.value = '';
        if (startDate) startDate.value = '';
        if (endDate) endDate.value = '';
        this.loadAuditLogs(1);
    }

    async loadAuditFilters() {
        try {
            const res = await fetch('/api/audit/filters');
            const data = await res.json();
            if (!data.success) return;

            const resourceSelect = document.getElementById('audit-resource-type');
            if (resourceSelect && data.resource_types) {
                data.resource_types.forEach(rt => {
                    const opt = document.createElement('option');
                    opt.value = rt;
                    opt.textContent = rt;
                    resourceSelect.appendChild(opt);
                });
            }

            const actionSelect = document.getElementById('audit-action');
            if (actionSelect && data.actions) {
                data.actions.forEach(a => {
                    const opt = document.createElement('option');
                    opt.value = a;
                    opt.textContent = a;
                    actionSelect.appendChild(opt);
                });
            }

            const userSelect = document.getElementById('audit-user');
            if (userSelect && data.users) {
                data.users.forEach(u => {
                    const opt = document.createElement('option');
                    opt.value = u.user_id;
                    opt.textContent = u.username;
                    userSelect.appendChild(opt);
                });
            }
        } catch (e) {
            console.error('审计筛选选项加载失败:', e);
        }
    }

    renderAuditStats(total) {
        const container = document.getElementById('audit-stats');
        if (!container) return;
        container.innerHTML = this.t('common.total', { count: '<strong>' + total + '</strong>' });
    }

    renderAuditTable(logs) {
        const tbody = document.getElementById('audit-tbody');
        if (!tbody) return;

        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:40px;">' + this.t('audit.none') + '</td></tr>';
            return;
        }

        const actionLabelMap = {
            'create': '创建', 'update': '修改', 'delete': '删除',
            'login': '登录', 'logout': '登出', 'export': '导出',
            'toggle': '切换', 'archive': '归档', 'assign': '分配',
            'resolve': '解决', 'close': '关闭', 'submit': '提交',
            'invite': '邀请', 'change_role': '角色变更', 'bind': '绑定',
            'import': '导入', 'publish': '发布', 'review': '审核',
            'lifecycle_review': '提交审核', 'lifecycle_publish': '发布',
            'lifecycle_pause': '暂停', 'lifecycle_resume': '恢复运行',
            'lifecycle_expire': '标记失效', 'lifecycle_archive': '归档',
            'lifecycle_delete': '删除', 'batch_import': '批量导入'
        };

        tbody.innerHTML = logs.map(log => {
            const timeStr = (log.created_at || '').slice(0, 19).replace('T', ' ');
            const actionLabel = actionLabelMap[log.action] || log.action;
            const actionClass = log.action.split('_')[0].split('_')[0];
            const resourceName = log.resource_type
                ? (log.resource_type + (log.resource_id ? ' #' + log.resource_id : ''))
                : '';

            return '<tr>'
                + '<td>' + timeStr + '</td>'
                + '<td>' + this.escapeHtml(log.username) + '</td>'
                + '<td><span class="audit-action-badge ' + actionClass + '">' + this.escapeHtml(actionLabel) + '</span></td>'
                + '<td>' + this.escapeHtml(resourceName) + '</td>'
                + '<td style="font-family:monospace;font-size:12px;">' + (log.ip || '') + '</td>'
                + '<td><a class="audit-detail-link" onclick="event.stopPropagation();app.showAuditDetail(' + log.id + ')">' + this.t('audit.viewDetail') + '</a></td>'
                + '</tr>';
        }).join('');
    }

    renderAuditPagination(currentPage, totalPages, total) {
        const container = document.getElementById('audit-pagination');
        if (!container || totalPages <= 1) {
            if (container) container.innerHTML = '';
            return;
        }

        let html = '';
        html += '<button ' + (currentPage <= 1 ? 'disabled' : '') + ' onclick="app.loadAuditLogs(' + (currentPage - 1) + ')">' + this.t('common.prevPage') + '</button>';

        const maxVisible = 7;
        let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
        let end = Math.min(totalPages, start + maxVisible - 1);
        if (end - start < maxVisible - 1) {
            start = Math.max(1, end - maxVisible + 1);
        }

        if (start > 1) {
            html += '<button onclick="app.loadAuditLogs(1)">1</button>';
            if (start > 2) html += '<span class="page-info">...</span>';
        }

        for (let i = start; i <= end; i++) {
            html += '<button class="' + (i === currentPage ? 'active' : '') + '" onclick="app.loadAuditLogs(' + i + ')">' + i + '</button>';
        }

        if (end < totalPages) {
            if (end < totalPages - 1) html += '<span class="page-info">...</span>';
            html += '<button onclick="app.loadAuditLogs(' + totalPages + ')">' + totalPages + '</button>';
        }

        html += '<button ' + (currentPage >= totalPages ? 'disabled' : '') + ' onclick="app.loadAuditLogs(' + (currentPage + 1) + ')">' + this.t('common.nextPage') + '</button>';
        html += '<span class="page-info">' + currentPage + '/' + totalPages + '</span>';

        container.innerHTML = html;
    }

    async showAuditDetail(logId) {
        try {
            const res = await fetch('/api/audit/' + logId);
            const data = await res.json();
            if (!data.success) return;

            const log = data.log;
            const body = document.getElementById('audit-detail-body');
            if (!body) return;

            const actionLabelMap = {
                'create': '创建', 'update': '修改', 'delete': '删除',
                'login': '登录', 'logout': '登出', 'export': '导出'
            };

            let html = '';
            html += '<div class="audit-detail-section"><h4>' + this.t('common.action') + '</h4><p>' + this.escapeHtml(actionLabelMap[log.action] || log.action) + '</p></div>';
            html += '<div class="audit-detail-section"><h4>' + this.t('common.user') + '</h4><p>' + this.escapeHtml(log.username) + '</p></div>';
            html += '<div class="audit-detail-section"><h4>' + this.t('common.resource') + '</h4><p>' + this.escapeHtml((log.resource_type || '') + (log.resource_id ? ' #' + log.resource_id : '')) + '</p></div>';
            html += '<div class="audit-detail-section"><h4>' + this.t('common.time') + '</h4><p>' + (log.created_at || '') + '</p></div>';
            html += '<div class="audit-detail-section"><h4>' + this.t('common.ipAddress') + '</h4><p style="font-family:monospace;">' + (log.ip || '') + '</p></div>';

            if (log.detail) {
                html += '<div class="audit-detail-section"><h4>' + this.t('common.detail') + '</h4><div class="audit-json-view">' + this.escapeHtml(typeof log.detail === 'string' ? log.detail : JSON.stringify(log.detail, null, 2)) + '</div></div>';
            }

            if (log.before_data || log.after_data) {
                html += '<div class="audit-detail-section"><h4>' + this.t('audit.dataChangeDiff') + '</h4>';
                html += '<div class="audit-diff-container">';
                html += '<div class="audit-diff-panel before"><h5>' + this.t('audit.before') + '</h5><pre>' + this.escapeHtml(log.before_data ? (typeof log.before_data === 'string' ? log.before_data : JSON.stringify(log.before_data, null, 2)) : '无') + '</pre></div>';
                html += '<div class="audit-diff-panel after"><h5>' + this.t('audit.after') + '</h5><pre>' + this.escapeHtml(log.after_data ? (typeof log.after_data === 'string' ? log.after_data : JSON.stringify(log.after_data, null, 2)) : '无') + '</pre></div>';
                html += '</div></div>';
            }

            if (log.user_agent) {
                html += '<div class="audit-detail-section"><h4>' + this.t('common.userAgent') + '</h4><p style="font-size:12px;word-break:break-all;">' + this.escapeHtml(log.user_agent) + '</p></div>';
            }

            body.innerHTML = html;
            document.getElementById('audit-detail-modal').classList.add('active');
        } catch (e) {
            console.error('审计详情加载失败:', e);
        }
    }

    // ============ 回收站 ============

    async loadRecycle(page = 1) {
        if (!this.isAuthenticated) return;

        try {
            const params = new URLSearchParams();
            params.set('page', page);
            params.set('size', '20');

            const keyword = document.getElementById('recycle-keyword')?.value.trim();
            const type = document.getElementById('recycle-type')?.value;

            if (keyword) params.set('keyword', keyword);
            if (type) params.set('type', type);

            const res = await fetch('/api/recycle?' + params.toString());
            const data = await res.json();
            if (!data.success) return;

            this.renderRecycleTable(data.items);
            this.renderRecyclePagination(data.page, data.total_pages, data.total);
            this.updateRecycleBatchButtons();
        } catch (e) {
            console.error('回收站加载失败:', e);
        }
    }

    renderRecycleTable(items) {
        const tbody = document.getElementById('recycle-tbody');
        if (!tbody) return;

        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:40px;">' + this.t('recycle.empty') + '</td></tr>';
            return;
        }

        const now = new Date();
        const typeLabelMap = {
            'qrcode': '二维码', 'form': '表单', 'file': '文件',
            'workorder': '工单', 'inspection': '巡检'
        };

        tbody.innerHTML = items.map(item => {
            const deletedAt = item.deleted_at ? new Date(item.deleted_at) : null;
            const daysLeft = deletedAt ? Math.max(0, 30 - Math.floor((now - deletedAt) / (1000 * 60 * 60 * 24))) : 0;
            let daysClass = 'safe';
            if (daysLeft <= 3) daysClass = 'danger';
            else if (daysLeft <= 7) daysClass = 'warning';

            const timeStr = (item.deleted_at || '').slice(0, 19).replace('T', ' ');

            return '<tr>'
                + '<td><input type="checkbox" class="recycle-checkbox" data-id="' + item.id + '" data-type="' + item.resource_type + '" onchange="app.updateRecycleBatchButtons()"></td>'
                + '<td>' + this.escapeHtml(item.name) + '</td>'
                + '<td><span class="recycle-type-badge ' + item.resource_type + '">' + (typeLabelMap[item.resource_type] || item.resource_type) + '</span></td>'
                + '<td>' + timeStr + '</td>'
                + '<td>' + this.escapeHtml(item.deleted_by_name || '') + '</td>'
                + '<td><span class="days-left ' + daysClass + '">' + daysLeft + ' 天</span></td>'
                + '<td>'
                + '<button class="recycle-action-btn" onclick="app.recycleRestore(' + item.id + ",'" + item.resource_type + '\')">' + this.t('recycle.restore') + '</button>'
                + '<button class="recycle-action-btn permanent-delete" onclick="app.recyclePermanentDelete(' + item.id + ",'" + item.resource_type + '\')">' + this.t('recycle.permanentDelete') + '</button>'
                + '</td>'
                + '</tr>';
        }).join('');
    }

    renderRecyclePagination(currentPage, totalPages, total) {
        const container = document.getElementById('recycle-pagination');
        if (!container || totalPages <= 1) {
            if (container) container.innerHTML = '';
            return;
        }

        let html = '';
        html += '<button ' + (currentPage <= 1 ? 'disabled' : '') + ' onclick="app.loadRecycle(' + (currentPage - 1) + ')">' + this.t('common.prevPage') + '</button>';

        const maxVisible = 7;
        let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
        let end = Math.min(totalPages, start + maxVisible - 1);
        if (end - start < maxVisible - 1) {
            start = Math.max(1, end - maxVisible + 1);
        }

        if (start > 1) {
            html += '<button onclick="app.loadRecycle(1)">1</button>';
            if (start > 2) html += '<span class="page-info">...</span>';
        }

        for (let i = start; i <= end; i++) {
            html += '<button class="' + (i === currentPage ? 'active' : '') + '" onclick="app.loadRecycle(' + i + ')">' + i + '</button>';
        }

        if (end < totalPages) {
            if (end < totalPages - 1) html += '<span class="page-info">...</span>';
            html += '<button onclick="app.loadRecycle(' + totalPages + ')">' + totalPages + '</button>';
        }

        html += '<button ' + (currentPage >= totalPages ? 'disabled' : '') + ' onclick="app.loadRecycle(' + (currentPage + 1) + ')">' + this.t('common.nextPage') + '</button>';
        html += '<span class="page-info">' + currentPage + '/' + totalPages + '</span>';

        container.innerHTML = html;
    }

    recycleToggleAll() {
        const selectAll = document.getElementById('recycle-select-all');
        const checkboxes = document.querySelectorAll('.recycle-checkbox');
        checkboxes.forEach(cb => { cb.checked = selectAll.checked; });
        this.updateRecycleBatchButtons();
    }

    updateRecycleBatchButtons() {
        const checkboxes = document.querySelectorAll('.recycle-checkbox:checked');
        const restoreBtn = document.getElementById('recycle-batch-restore-btn');
        const deleteBtn = document.getElementById('recycle-batch-delete-btn');
        const hasSelection = checkboxes.length > 0;
        if (restoreBtn) restoreBtn.disabled = !hasSelection;
        if (deleteBtn) deleteBtn.disabled = !hasSelection;
    }

    getSelectedRecycleItems() {
        const checkboxes = document.querySelectorAll('.recycle-checkbox:checked');
        const items = [];
        checkboxes.forEach(cb => {
            items.push({ id: parseInt(cb.dataset.id), type: cb.dataset.type });
        });
        return items;
    }

    async recycleRestore(id, type) {
        try {
            const res = await fetch('/api/recycle/restore', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: [{ id: id, type: type }] })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message || '恢复成功', 'success');
                this.loadRecycle();
            } else {
                this.showNotification(data.error || this.t('toast.restoreFailed', '恢复失败'), 'error');
            }
        } catch (e) {
            console.error('恢复失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async recyclePermanentDelete(id, type) {
        if (!confirm(this.t('error.confirmPermanentDelete'))) return;

        try {
            const res = await fetch('/api/recycle/permanent-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: [{ id: id, type: type }] })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message || this.t('toast.deleteSuccess', '删除成功'), 'success');
                this.loadRecycle();
            } else {
                this.showNotification(data.error || this.t('toast.deleteFailed', '删除失败'), 'error');
            }
        } catch (e) {
            console.error('彻底删除失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async recycleBatchRestore() {
        const items = this.getSelectedRecycleItems();
        if (items.length === 0) {
            this.showNotification('请选择要恢复的项目', 'warning');
            return;
        }

        try {
            const res = await fetch('/api/recycle/restore', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: items })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message || '批量恢复成功', 'success');
                this.loadRecycle();
                document.getElementById('recycle-select-all').checked = false;
            } else {
                this.showNotification(data.error || this.t('toast.batchRestoreFailed', '批量恢复失败'), 'error');
            }
        } catch (e) {
            console.error('批量恢复失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async recycleBatchDelete() {
        const items = this.getSelectedRecycleItems();
        if (items.length === 0) {
            this.showNotification('请选择要删除的项目', 'warning');
            return;
        }

        if (!confirm(this.t('error.confirmDeleteSelected', { count: items.length }))) return;

        try {
            const res = await fetch('/api/recycle/permanent-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: items })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message || '批量删除成功', 'success');
                this.loadRecycle();
                document.getElementById('recycle-select-all').checked = false;
            } else {
                this.showNotification(data.error || this.t('toast.batchDeleteFailed', '批量删除失败'), 'error');
            }
        } catch (e) {
            console.error('批量删除失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async recycleCleanup() {
        if (!confirm(this.t('error.confirmCleanup'))) return;

        try {
            const res = await fetch('/api/recycle/cleanup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message || '清理完成', 'success');
                this.loadRecycle();
            } else {
                this.showNotification(data.error || this.t('toast.cleanupFailed', '清理失败'), 'error');
            }
        } catch (e) {
            console.error('清理失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    // ========== 组织架构管理 ==========

    orgTreeData = [];
    orgSelectedNode = null;
    orgDetailTab = 'info';
    orgNodeTypes = [];
    orgExpandedNodes = new Set();
    orgMemberPage = 1;
    orgMemberSelected = new Set();

    async orgLoadTree() {
        try {
            const res = await fetch('/api/org/tree');
            const data = await res.json();
            if (data.success) {
                this.orgTreeData = data.data.tree || [];
                this.orgRenderTree();
            }
        } catch (e) {
            console.error('加载组织树失败:', e);
        }
    }

    orgRenderTree() {
        const wrapper = document.getElementById('org-tree-wrapper');
        if (!wrapper) return;
        const keyword = (document.getElementById('org-search-input')?.value || '').trim().toLowerCase();
        wrapper.innerHTML = '';
        const renderNodes = (nodes, level) => {
            nodes.forEach(node => {
                const matched = !keyword || node.name.toLowerCase().includes(keyword);
                const matchChildren = keyword && !matched && this._orgHasMatchingChild(node, keyword);
                if (keyword && !matched && !matchChildren) return;

                const div = document.createElement('div');
                div.className = 'org-tree-node';
                div.draggable = true;
                div.dataset.nodeId = node.id;
                div.dataset.parentId = node.parent_id || '';

                const content = document.createElement('div');
                content.className = 'org-tree-node-content';
                content.style.paddingLeft = (level * 16 + 8) + 'px';
                if (this.orgSelectedNode && this.orgSelectedNode.id === node.id) {
                    content.classList.add('active');
                }

                const toggle = document.createElement('button');
                toggle.className = 'org-tree-toggle';
                toggle.textContent = '▶';
                if (!node.has_children && (!node.children || node.children.length === 0)) {
                    toggle.classList.add('empty');
                }
                if (this.orgExpandedNodes.has(node.id)) {
                    toggle.classList.add('expanded');
                }
                toggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.orgToggleNode(node.id);
                });

                const icon = document.createElement('span');
                icon.className = 'org-tree-node-icon';
                const icons = { group: '🏛', company: '🏢', division: '🏭', department: '📂', team: '👥', center: '🎯' };
                icon.textContent = icons[node.node_type] || '📁';

                const name = document.createElement('span');
                name.className = 'org-tree-node-name';
                name.textContent = node.name;

                const count = document.createElement('span');
                count.className = 'org-tree-node-count';
                count.textContent = (node.member_count || 0) + '人';

                const actions = document.createElement('span');
                actions.className = 'org-tree-node-actions';
                const addBtn = document.createElement('button');
                addBtn.className = 'org-tree-node-action-btn';
                addBtn.textContent = '+';
                addBtn.title = '新建子节点';
                addBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.orgCreateChild(node.id);
                });
                const editBtn = document.createElement('button');
                editBtn.className = 'org-tree-node-action-btn';
                editBtn.textContent = '✎';
                editBtn.title = '编辑';
                editBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.orgEditNode(node);
                });
                actions.appendChild(addBtn);
                actions.appendChild(editBtn);

                content.appendChild(toggle);
                content.appendChild(icon);
                content.appendChild(name);
                content.appendChild(count);
                content.appendChild(actions);

                content.addEventListener('click', () => this.orgSelectNode(node));
                content.addEventListener('dragstart', (e) => this._orgDragStart(e, node));
                content.addEventListener('dragover', (e) => this._orgDragOver(e, node));
                content.addEventListener('dragleave', (e) => this._orgDragLeave(e));
                content.addEventListener('drop', (e) => this._orgDrop(e, node));

                div.appendChild(content);

                if (node.children && node.children.length > 0) {
                    const childrenDiv = document.createElement('div');
                    childrenDiv.className = 'org-tree-children';
                    if (!this.orgExpandedNodes.has(node.id)) {
                        childrenDiv.style.display = 'none';
                    }
                    const childNodes = renderNodes(node.children, level + 1);
                    childNodes.forEach(cn => childrenDiv.appendChild(cn));
                    div.appendChild(childrenDiv);
                }

                wrapper.appendChild(div);
            });
            return [];
        };
        renderNodes(this.orgTreeData, 0);
    }

    _orgHasMatchingChild(node, keyword) {
        if (!node.children) return false;
        for (const child of node.children) {
            if (child.name.toLowerCase().includes(keyword)) return true;
            if (this._orgHasMatchingChild(child, keyword)) return true;
        }
        return false;
    }

    orgToggleNode(nodeId) {
        if (this.orgExpandedNodes.has(nodeId)) {
            this.orgExpandedNodes.delete(nodeId);
        } else {
            this.orgExpandedNodes.add(nodeId);
        }
        this.orgRenderTree();
    }

    orgFilterTree() {
        this.orgRenderTree();
    }

    async orgSelectNode(node) {
        this.orgSelectedNode = node;
        this.orgMemberPage = 1;
        this.orgDetailTab = 'info';
        this.orgMemberSelected.clear();
        this.orgRenderTree();
        await this.orgLoadDetail();
    }

    async orgLoadDetail() {
        if (!this.orgSelectedNode) return;
        const panel = document.getElementById('org-right-panel');
        if (!panel) return;

        const node = this.orgSelectedNode;
        panel.innerHTML = `
            <div class="org-detail-header">
                <div class="org-detail-title">
                    <h2>${this._escapeHtml(node.name)}</h2>
                    <span class="org-detail-type">${node.node_type_label || node.node_type}</span>
                </div>
                <div class="org-detail-actions">
                    <button class="btn-secondary btn-sm" onclick="app.orgCreateChild(${node.id})">+ 新建子节点</button>
                    <button class="btn-secondary btn-sm" onclick="app.orgEditNode(app.orgSelectedNode)">编辑</button>
                    <button class="btn-danger btn-sm" onclick="app.orgDeleteNode(${node.id})">删除</button>
                </div>
            </div>
            <div class="org-detail-tabs">
                <button class="org-detail-tab active" data-tab="info" onclick="app.orgSwitchDetailTab('info')">基本信息</button>
                <button class="org-detail-tab" data-tab="members" onclick="app.orgSwitchDetailTab('members')">成员</button>
                <button class="org-detail-tab" data-tab="permissions" onclick="app.orgSwitchDetailTab('permissions')">权限</button>
            </div>
            <div class="org-detail-tab-content active" id="org-tab-info">
                ${this._orgBuildInfoHTML(node)}
            </div>
            <div class="org-detail-tab-content" id="org-tab-members"></div>
            <div class="org-detail-tab-content" id="org-tab-permissions"></div>`;

        if (this.orgDetailTab === 'members') await this.orgLoadMembers();
        if (this.orgDetailTab === 'permissions') await this.orgLoadPermissions();
    }

    _orgBuildInfoHTML(node) {
        return `
            <div class="org-info-grid">
                <div class="org-info-item">
                    <div class="org-info-label">节点类型</div>
                    <div class="org-info-value">${this._escapeHtml(node.node_type_label || node.node_type)}</div>
                </div>
                <div class="org-info-item">
                    <div class="org-info-label">层级深度</div>
                    <div class="org-info-value">第 ${node.depth} 层</div>
                </div>
                <div class="org-info-item">
                    <div class="org-info-label">成员数量</div>
                    <div class="org-info-value">${node.member_count || 0} 人</div>
                </div>
                <div class="org-info-item">
                    <div class="org-info-label">负责人</div>
                    <div class="org-info-value">${this._escapeHtml(node.leader_name || '未设置')}</div>
                </div>
                <div class="org-info-item">
                    <div class="org-info-label">子节点数</div>
                    <div class="org-info-value">${(node.children || []).length} 个</div>
                </div>
                <div class="org-info-item">
                    <div class="org-info-label">排序</div>
                    <div class="org-info-value">${node.sort_order || 0}</div>
                </div>
                <div class="org-info-item" style="grid-column: 1 / -1;">
                    <div class="org-info-label">描述</div>
                    <div class="org-info-value">${this._escapeHtml(node.description || '暂无描述')}</div>
                </div>
            </div>`;
    }

    async orgSwitchDetailTab(tab) {
        this.orgDetailTab = tab;
        const panel = document.getElementById('org-right-panel');
        if (!panel) return;
        panel.querySelectorAll('.org-detail-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        panel.querySelectorAll('.org-detail-tab-content').forEach(c => c.classList.toggle('active', c.id === 'org-tab-' + tab));

        if (tab === 'members') await this.orgLoadMembers();
        if (tab === 'permissions') await this.orgLoadPermissions();
    }

    async orgLoadMembers() {
        if (!this.orgSelectedNode) return;
        const container = document.getElementById('org-tab-members');
        if (!container) return;

        try {
            const keyword = document.getElementById('org-member-search-input')?.value?.trim() || '';
            const res = await fetch(`/api/org/nodes/${this.orgSelectedNode.id}/members?page=${this.orgMemberPage}&size=50&keyword=${encodeURIComponent(keyword)}`);
            const data = await res.json();
            if (!data.success) { container.innerHTML = '<p style="color:var(--text-muted);">加载失败</p>'; return; }

            const { members, total, page, total_pages } = data.data;
            const selectedIds = Array.from(this.orgMemberSelected);

            container.innerHTML = `
                <div class="org-member-toolbar">
                    <div class="org-member-search">
                        <input type="text" id="org-member-search-input" placeholder="搜索成员..." onkeydown="if(event.key==='Enter')app.orgLoadMembers()">
                        <button class="btn-secondary btn-sm" onclick="app.orgMemberPage=1;app.orgLoadMembers()">搜索</button>
                    </div>
                    <div class="org-member-batch-actions">
                        <button class="btn-secondary btn-sm" onclick="app.orgShowAddMembers()">+ 添加成员</button>
                        <button class="btn-secondary btn-sm" onclick="app.orgRemoveMembers()" ${selectedIds.length === 0 ? 'disabled' : ''}>移除选中</button>
                        <button class="btn-secondary btn-sm" onclick="app.orgShowTransferMembers()" ${selectedIds.length === 0 ? 'disabled' : ''}>转移选中</button>
                    </div>
                </div>
                <table class="org-member-table">
                    <thead>
                        <tr>
                            <th style="width:40px;"><input type="checkbox" class="org-member-checkbox" onchange="app.orgToggleAllMembers(this)" ${members.length === 0 ? 'disabled' : ''}></th>
                            <th>用户名</th>
                            <th>邮箱</th>
                            <th>角色</th>
                            <th>主部门</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${members.length === 0 ? '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:30px;">暂无成员</td></tr>' : ''}
                        ${members.map(m => `
                            <tr>
                                <td><input type="checkbox" class="org-member-checkbox" value="${m.user_id}" onchange="app.orgToggleMember(${m.user_id}, this)" ${selectedIds.includes(String(m.user_id)) ? 'checked' : ''}></td>
                                <td>${this._escapeHtml(m.username)}</td>
                                <td>${this._escapeHtml(m.email || '')}</td>
                                <td><span class="org-member-role-badge">${this._escapeHtml(m.role_type || 'member')}</span></td>
                                <td>${m.is_primary ? '<span class="org-member-primary-badge">主部门</span>' : ''}</td>
                            </tr>`).join('')}
                    </tbody>
                </table>
                <div class="org-member-pagination">
                    <button onclick="app.orgMemberPage=1;app.orgLoadMembers()" ${page <= 1 ? 'disabled' : ''}>首页</button>
                    <button onclick="app.orgMemberPage--;app.orgLoadMembers()" ${page <= 1 ? 'disabled' : ''}>上一页</button>
                    <span>${page} / ${total_pages} (共${total}人)</span>
                    <button onclick="app.orgMemberPage++;app.orgLoadMembers()" ${page >= total_pages ? 'disabled' : ''}>下一页</button>
                    <button onclick="app.orgMemberPage=${total_pages};app.orgLoadMembers()" ${page >= total_pages ? 'disabled' : ''}>末页</button>
                </div>`;
        } catch (e) {
            console.error('加载成员失败:', e);
            container.innerHTML = '<p style="color:var(--text-muted);">加载失败</p>';
        }
    }

    orgToggleAllMembers(checkbox) {
        const container = document.getElementById('org-tab-members');
        if (!container) return;
        const checkboxes = container.querySelectorAll('.org-member-checkbox');
        checkboxes.forEach(cb => {
            if (cb === checkbox) return;
            cb.checked = checkbox.checked;
            this.orgToggleMember(parseInt(cb.value), cb);
        });
    }

    orgToggleMember(userId, checkbox) {
        if (checkbox.checked) {
            this.orgMemberSelected.add(String(userId));
        } else {
            this.orgMemberSelected.delete(String(userId));
        }
        this._orgUpdateBatchButtons();
    }

    _orgUpdateBatchButtons() {
        const container = document.getElementById('org-tab-members');
        if (!container) return;
        const selected = this.orgMemberSelected.size;
        container.querySelectorAll('.org-member-batch-actions button').forEach(btn => {
            if (btn.textContent.includes('移除') || btn.textContent.includes('转移')) {
                btn.disabled = selected === 0;
            }
        });
    }

    async orgShowAddMembers() {
        const overlay = this._orgCreateModal('添加成员', `
            <div class="form-group">
                <label>搜索用户</label>
                <input type="text" id="org-add-user-search" placeholder="输入用户名或邮箱搜索..." oninput="app.orgSearchUsers()">
            </div>
            <div class="org-user-selector" id="org-user-selector-list">
                <p style="text-align:center;color:var(--text-muted);padding:20px;">输入关键词搜索用户</p>
            </div>`, async () => {
                const selected = overlay.querySelectorAll('.org-user-selector-item.selected');
                const userIds = Array.from(selected).map(el => parseInt(el.dataset.userId));
                if (userIds.length === 0) { this.showNotification('请选择至少一个用户', 'warning'); return; }
                await this.orgAddMembers(userIds);
                this._orgCloseModal();
            });
    }

    async orgSearchUsers() {
        const input = document.getElementById('org-add-user-search');
        const list = document.getElementById('org-user-selector-list');
        const keyword = (input?.value || '').trim();
        if (!list) return;

        if (!keyword) {
            list.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:20px;">输入关键词搜索用户</p>';
            return;
        }

        try {
            const res = await fetch(`/api/org/users/search?keyword=${encodeURIComponent(keyword)}&size=20`);
            const data = await res.json();
            if (!data.success) return;

            list.innerHTML = data.data.users.map(u => `
                <div class="org-user-selector-item" data-user-id="${u.id}" onclick="this.classList.toggle('selected')">
                    <input type="checkbox" ${this.orgMemberSelected.has(String(u.id)) ? 'checked' : ''}>
                    <span>${this._escapeHtml(u.username)}</span>
                    <span style="font-size:12px;color:var(--text-muted);">${this._escapeHtml(u.email || '')}</span>
                </div>`).join('');
        } catch (e) {
            console.error('搜索用户失败:', e);
        }
    }

    async orgAddMembers(userIds) {
        try {
            const res = await fetch(`/api/org/nodes/${this.orgSelectedNode.id}/members`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_ids: userIds })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message, 'success');
                this.orgMemberSelected.clear();
                await this.orgLoadTree();
                await this.orgLoadMembers();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('添加成员失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async orgRemoveMembers() {
        if (this.orgMemberSelected.size === 0) return;
        if (!confirm(this.t('confirm.removeMembers', `确认移除选中的 ${this.orgMemberSelected.size} 名成员？`))) return;

        try {
            const res = await fetch(`/api/org/nodes/${this.orgSelectedNode.id}/members`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_ids: Array.from(this.orgMemberSelected).map(Number) })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message, 'success');
                this.orgMemberSelected.clear();
                await this.orgLoadTree();
                await this.orgLoadMembers();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('移除成员失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async orgShowTransferMembers() {
        if (this.orgMemberSelected.size === 0) return;
        let targetDeptId = null;

        const overlay = this._orgCreateModal('转移成员', `
            <p style="margin-bottom:12px;color:var(--text-secondary);">将选中的 ${this.orgMemberSelected.size} 名成员转移到目标部门</p>
            <div class="form-group">
                <label>目标部门</label>
                <select id="org-transfer-target" class="org-transfer-select">
                    <option value="">请选择目标部门</option>
                </select>
            </div>`, async () => {
                targetDeptId = parseInt(document.getElementById('org-transfer-target')?.value);
                if (!targetDeptId) { this.showNotification('请选择目标部门', 'warning'); return; }
                await this.orgTransferMembers(targetDeptId);
                this._orgCloseModal();
            });

        try {
            const res = await fetch('/api/org/tree');
            const data = await res.json();
            if (data.success) {
                const select = document.getElementById('org-transfer-target');
                const addOptions = (nodes, prefix) => {
                    nodes.forEach(n => {
                        if (n.id !== this.orgSelectedNode.id) {
                            select.innerHTML += `<option value="${n.id}">${prefix}${n.name}</option>`;
                        }
                        if (n.children) addOptions(n.children, prefix + '  ');
                    });
                };
                addOptions(data.data.tree, '');
            }
        } catch (e) { console.error(e); }
    }

    async orgTransferMembers(toDeptId) {
        try {
            const res = await fetch('/api/org/members/transfer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_ids: Array.from(this.orgMemberSelected).map(Number),
                    from_dept_id: this.orgSelectedNode.id,
                    to_dept_id: toDeptId
                })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(data.message, 'success');
                this.orgMemberSelected.clear();
                await this.orgLoadTree();
                await this.orgLoadMembers();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('转移成员失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async orgLoadPermissions() {
        if (!this.orgSelectedNode) return;
        const container = document.getElementById('org-tab-permissions');
        if (!container) return;

        try {
            const res = await fetch(`/api/org/nodes/${this.orgSelectedNode.id}/permissions`);
            const data = await res.json();
            if (!data.success) { container.innerHTML = '<p style="color:var(--text-muted);">加载失败</p>'; return; }

            const { effective_permissions, own_permissions, permission_keys } = data.data;
            container.innerHTML = `
                <div style="margin-bottom:12px;display:flex;gap:8px;">
                    <button class="btn-primary btn-sm" onclick="app.orgSavePermissions()">保存权限</button>
                </div>
                <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">权限从根节点逐级继承，子节点显式设置会覆盖继承结果。设置后保存。</p>
                <table class="org-perm-table">
                    <thead>
                        <tr>
                            <th>权限点</th>
                            <th>有效值</th>
                            <th>来源</th>
                            <th>当前设置</th>
                            <th>继承到子节点</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${permission_keys.map(key => {
                            const eff = effective_permissions[key] || {};
                            const own = own_permissions[key] || {};
                            const effValue = eff.value || 'deny';
                            const ownValue = own.value || '';
                            const source = eff.source || '-';
                            const inherit = own.inherit !== false;
                            return `
                                <tr>
                                    <td><code style="font-size:12px;">${key}</code></td>
                                    <td><span class="org-perm-value ${effValue}">${effValue === 'allow' ? '允许' : '拒绝'}</span></td>
                                    <td><span class="org-perm-source ${source}">${source === 'own' ? '自身设置' : (source === 'inherit' ? '继承' : '-')}</span></td>
                                    <td>
                                        <select class="org-perm-edit-select" data-perm-key="${key}">
                                            <option value="" ${!ownValue ? 'selected' : ''}>未设置</option>
                                            <option value="allow" ${ownValue === 'allow' ? 'selected' : ''}>允许</option>
                                            <option value="deny" ${ownValue === 'deny' ? 'selected' : ''}>拒绝</option>
                                        </select>
                                    </td>
                                    <td>
                                        <input type="checkbox" data-perm-key="${key}" data-inherit="true" ${inherit ? 'checked' : ''}>
                                    </td>
                                </tr>`;
                        }).join('')}
                    </tbody>
                </table>`;
        } catch (e) {
            console.error('加载权限失败:', e);
            container.innerHTML = '<p style="color:var(--text-muted);">' + this.t('toast.loadFailed', '加载失败') + '</p>';
        }
    }

    async orgSavePermissions() {
        const container = document.getElementById('org-tab-permissions');
        if (!container) return;
        const permissions = {};
        container.querySelectorAll('select[data-perm-key]').forEach(sel => {
            if (sel.value) {
                const key = sel.dataset.permKey;
                const inheritCheck = container.querySelector(`input[data-perm-key="${key}"][data-inherit]`);
                permissions[key] = {
                    value: sel.value,
                    inherit_to_children: inheritCheck ? inheritCheck.checked : true
                };
            }
        });

        try {
            const res = await fetch(`/api/org/nodes/${this.orgSelectedNode.id}/permissions`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ permissions })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification('权限保存成功', 'success');
                await this.orgLoadPermissions();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('保存权限失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async orgCreateRoot() {
        await this._orgLoadNodeTypes();
        const overlay = this._orgCreateModal('新建根节点', `
            <div class="form-group">
                <label>名称 *</label>
                <input type="text" id="org-node-name" placeholder="输入节点名称">
            </div>
            <div class="form-group">
                <label>节点类型</label>
                <select id="org-node-type">${this.orgNodeTypes.map(t => `<option value="${t.key}">${t.label}</option>`).join('')}</select>
            </div>
            <div class="form-group">
                <label>负责人</label>
                <input type="text" id="org-node-leader" placeholder="输入负责人姓名">
            </div>
            <div class="form-group">
                <label>描述</label>
                <textarea id="org-node-desc" placeholder="输入描述信息"></textarea>
            </div>`, async () => {
                await this._orgSubmitCreate(null);
                this._orgCloseModal();
            });
    }

    async orgCreateChild(parentId) {
        await this._orgLoadNodeTypes();
        const overlay = this._orgCreateModal('新建子节点', `
            <div class="form-group">
                <label>名称 *</label>
                <input type="text" id="org-node-name" placeholder="输入节点名称">
            </div>
            <div class="form-group">
                <label>节点类型</label>
                <select id="org-node-type">${this.orgNodeTypes.map(t => `<option value="${t.key}">${t.label}</option>`).join('')}</select>
            </div>
            <div class="form-group">
                <label>负责人</label>
                <input type="text" id="org-node-leader" placeholder="输入负责人姓名">
            </div>
            <div class="form-group">
                <label>描述</label>
                <textarea id="org-node-desc" placeholder="输入描述信息"></textarea>
            </div>`, async () => {
                await this._orgSubmitCreate(parentId);
                this._orgCloseModal();
            });
    }

    async _orgLoadNodeTypes() {
        if (this.orgNodeTypes.length > 0) return;
        try {
            const res = await fetch('/api/org/node-types');
            const data = await res.json();
            if (data.success) this.orgNodeTypes = data.data.types;
        } catch (e) { console.error(e); }
    }

    async _orgSubmitCreate(parentId) {
        const name = document.getElementById('org-node-name')?.value.trim();
        if (!name) { this.showNotification('请输入节点名称', 'warning'); return; }
        const nodeType = document.getElementById('org-node-type')?.value || 'department';
        const leaderName = document.getElementById('org-node-leader')?.value.trim() || '';
        const description = document.getElementById('org-node-desc')?.value.trim() || '';

        try {
            const res = await fetch('/api/org/nodes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, node_type: nodeType, parent_id: parentId, leader_name: leaderName, description })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(this.t('toast.createSuccess', '创建成功'), 'success');
                await this.orgLoadTree();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('创建节点失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async orgEditNode(node) {
        if (!node) node = this.orgSelectedNode;
        if (!node) return;
        await this._orgLoadNodeTypes();

        const overlay = this._orgCreateModal('编辑节点', `
            <div class="form-group">
                <label>名称 *</label>
                <input type="text" id="org-node-name" value="${this._escapeHtml(node.name)}" placeholder="输入节点名称">
            </div>
            <div class="form-group">
                <label>节点类型</label>
                <select id="org-node-type">${this.orgNodeTypes.map(t => `<option value="${t.key}" ${t.key === node.node_type ? 'selected' : ''}>${t.label}</option>`).join('')}</select>
            </div>
            <div class="form-group">
                <label>负责人</label>
                <input type="text" id="org-node-leader" value="${this._escapeHtml(node.leader_name || '')}" placeholder="输入负责人姓名">
            </div>
            <div class="form-group">
                <label>描述</label>
                <textarea id="org-node-desc" placeholder="输入描述信息">${this._escapeHtml(node.description || '')}</textarea>
            </div>
            <div class="form-group">
                <label>排序</label>
                <input type="number" id="org-node-sort" value="${node.sort_order || 0}" placeholder="数字越小越靠前">
            </div>`, async () => {
                await this._orgSubmitEdit(node.id);
                this._orgCloseModal();
            });
    }

    async _orgSubmitEdit(nodeId) {
        const name = document.getElementById('org-node-name')?.value.trim();
        if (!name) { this.showNotification('请输入节点名称', 'warning'); return; }

        const body = {
            name,
            node_type: document.getElementById('org-node-type')?.value,
            leader_name: document.getElementById('org-node-leader')?.value.trim() || '',
            description: document.getElementById('org-node-desc')?.value.trim() || '',
            sort_order: parseInt(document.getElementById('org-node-sort')?.value || '0')
        };

        try {
            const res = await fetch(`/api/org/nodes/${nodeId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification('编辑成功', 'success');
                await this.orgLoadTree();
                if (this.orgSelectedNode && this.orgSelectedNode.id === nodeId) {
                    Object.assign(this.orgSelectedNode, body);
                    await this.orgLoadDetail();
                }
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('编辑节点失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async orgDeleteNode(nodeId) {
        if (!confirm(this.t('error.confirmDeleteNode'))) return;

        try {
            const res = await fetch(`/api/org/nodes/${nodeId}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.success) {
                this.showNotification(this.t('toast.deleteSuccess', '删除成功'), 'success');
                this.orgSelectedNode = null;
                this.orgExpandedNodes.clear();
                document.getElementById('org-right-panel').innerHTML = `
                    <div class="org-empty-state">
                        <div class="org-empty-icon">🏢</div>
                        <p>请选择左侧组织节点查看详情</p>
                    </div>`;
                await this.orgLoadTree();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('删除节点失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    _orgDragStart(e, node) {
        e.dataTransfer.setData('text/plain', String(node.id));
        e.dataTransfer.effectAllowed = 'move';
        e.target.classList.add('dragging');
    }

    _orgDragOver(e, node) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        e.target.closest('.org-tree-node-content')?.classList.add('drag-over');
    }

    _orgDragLeave(e) {
        e.target.closest('.org-tree-node-content')?.classList.remove('drag-over');
    }

    async _orgDrop(e, targetNode) {
        e.preventDefault();
        e.target.closest('.org-tree-node-content')?.classList.remove('drag-over');
        const draggedId = parseInt(e.dataTransfer.getData('text/plain'));
        if (!draggedId || draggedId === targetNode.id) return;

        try {
            const res = await fetch(`/api/org/nodes/${draggedId}/move`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ parent_id: targetNode.id })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification('移动成功', 'success');
                await this.orgLoadTree();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('移动节点失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
    }

    async orgExport() {
        try {
            window.open('/api/org/export', '_blank');
        } catch (e) {
            console.error('导出失败:', e);
            this.showNotification(this.t('toast.exportFailed', '导出失败'), 'error');
        }
    }

    async orgImport(event) {
        const file = event.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/org/import', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (data.success) {
                let msg = data.message;
                if (data.errors && data.errors.length > 0) {
                    msg += '\n错误详情:\n' + data.errors.slice(0, 10).join('\n');
                    if (data.errors.length > 10) msg += `\n...还有${data.errors.length - 10}条错误`;
                }
                alert(msg);
                this.showNotification(data.message, data.errors && data.errors.length > 0 ? 'warning' : 'success');
                await this.orgLoadTree();
            } else {
                this.showNotification(data.error, 'error');
            }
        } catch (e) {
            console.error('导入失败:', e);
            this.showNotification(this.t('toast.networkError', '网络请求失败'), 'error');
        }
        event.target.value = '';
    }

    _orgCreateModal(title, bodyHTML, onConfirm) {
        this._orgCloseModal();
        const overlay = document.createElement('div');
        overlay.className = 'org-modal-overlay';
        overlay.id = 'org-modal-overlay';
        overlay.innerHTML = `
            <div class="org-modal">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
                    <h3 style="margin:0;">${this._escapeHtml(title)}</h3>
                    <button style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-muted);" onclick="app._orgCloseModal()">&times;</button>
                </div>
                ${bodyHTML}
                <div class="org-modal-footer">
                    <button class="btn-secondary" onclick="app._orgCloseModal()">取消</button>
                    <button class="btn-primary" id="org-modal-confirm-btn">确认</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) this._orgCloseModal();
        });
        document.getElementById('org-modal-confirm-btn').addEventListener('click', onConfirm);
        return overlay;
    }

    _orgCloseModal() {
        const overlay = document.getElementById('org-modal-overlay');
        if (overlay) overlay.remove();
    }

    _escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    goToSection(section) {
        const tabMap = { inspection: 'lifecycle', workorders: 'lifecycle', forms: 'lifecycle', qrcodes: 'lifecycle' };
        this.switchTab(tabMap[section] || section);
    }

    // ============ 开放平台 ============

    openplatformApps = [];
    openplatformCurrentAppId = null;
    openplatformDetailTab = 'info';

    async openplatformLoadApps() {
        try {
            document.getElementById('oplatform-app-list').innerHTML = '<div class="oplatform-loading">加载中...</div>';
            const res = await fetch('/api/openplatform/apps');
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.openplatformApps = data.data.apps || [];
            this.openplatformRenderAppList();
            if (this.openplatformCurrentAppId) {
                const found = this.openplatformApps.find(a => a.id === this.openplatformCurrentAppId);
                if (!found) {
                    this.openplatformCurrentAppId = null;
                    document.getElementById('oplatform-right-panel').innerHTML =
                        '<div class="oplatform-empty-state"><div class="oplatform-empty-icon">🔌</div><p>请选择左侧应用查看详情</p></div>';
                }
            }
        } catch (e) {
            this.showNotification(this.t('toast.loadAppsFailed', '加载应用列表失败') + ': ' + e.message, 'error');
        }
    }

    openplatformRenderAppList() {
        const container = document.getElementById('oplatform-app-list');
        if (this.openplatformApps.length === 0) {
            container.innerHTML = '<div class="oplatform-loading">暂无应用，点击上方按钮创建</div>';
            return;
        }
        container.innerHTML = this.openplatformApps.map(a => `
            <div class="oplatform-app-item ${this.openplatformCurrentAppId === a.id ? 'active' : ''}"
                 onclick="app.openplatformSelectApp(${a.id})">
                <div class="app-name">${this._escapeHtml(a.app_name)}</div>
                <div class="app-key">${this._escapeHtml(a.app_key)}</div>
                <span class="app-status ${a.is_enabled ? 'enabled' : 'disabled'}">${a.is_enabled ? '启用' : '禁用'}</span>
            </div>
        `).join('');
    }

    openplatformSelectApp(appId) {
        this.openplatformCurrentAppId = appId;
        this.openplatformRenderAppList();
        this.openplatformRenderDetail();
    }

    openplatformRenderDetail() {
        const app = this.openplatformApps.find(a => a.id === this.openplatformCurrentAppId);
        if (!app) return;
        const panel = document.getElementById('oplatform-right-panel');
        panel.innerHTML = `
            <div class="oplatform-detail">
                <div class="oplatform-detail-header">
                    <h3>${this._escapeHtml(app.app_name)}</h3>
                    <span class="app-status-badge ${app.is_enabled ? 'enabled' : 'disabled'}">${app.is_enabled ? '🟢 启用' : '🔴 禁用'}</span>
                </div>
                <div class="oplatform-detail-tabs">
                    <button class="oplatform-detail-tab ${this.openplatformDetailTab === 'info' ? 'active' : ''}" onclick="app.openplatformSwitchTab('info')">基本信息</button>
                    <button class="oplatform-detail-tab ${this.openplatformDetailTab === 'stats' ? 'active' : ''}" onclick="app.openplatformSwitchTab('stats')">调用统计</button>
                    <button class="oplatform-detail-tab ${this.openplatformDetailTab === 'logs' ? 'active' : ''}" onclick="app.openplatformSwitchTab('logs')">调用日志</button>
                </div>
                <div class="oplatform-detail-body" id="oplatform-detail-body">
                    ${this.openplatformBuildTabContent(app)}
                </div>
            </div>
        `;
    }

    openplatformSwitchTab(tab) {
        this.openplatformDetailTab = tab;
        this.openplatformRenderDetail();
        if (tab === 'stats') this.openplatformLoadStats();
        if (tab === 'logs') this.openplatformLoadLogs(1);
    }

    openplatformBuildTabContent(app) {
        if (this.openplatformDetailTab === 'info') {
            return `
                <div class="oplatform-info-grid">
                    <div class="oplatform-info-item">
                        <div class="oplatform-info-label">应用名称</div>
                        <div class="oplatform-info-value">${this._escapeHtml(app.app_name)}</div>
                    </div>
                    <div class="oplatform-info-item">
                        <div class="oplatform-info-label">状态</div>
                        <div class="oplatform-info-value">${app.is_enabled ? '启用' : '禁用'}</div>
                    </div>
                    <div class="oplatform-info-item full-width">
                        <div class="oplatform-info-label">App Key</div>
                        <div class="oplatform-info-value mono">${this._escapeHtml(app.app_key)}</div>
                    </div>
                    <div class="oplatform-info-item">
                        <div class="oplatform-info-label">限流配额</div>
                        <div class="oplatform-info-value">${app.rate_limit_qpm} 次/分钟</div>
                    </div>
                    <div class="oplatform-info-item">
                        <div class="oplatform-info-label">创建时间</div>
                        <div class="oplatform-info-value">${app.created_at || '-'}</div>
                    </div>
                    <div class="oplatform-info-item full-width">
                        <div class="oplatform-info-label">IP白名单（每行一个IP）</div>
                        <textarea id="oplatform-ip-whitelist" class="oplatform-info-value" style="width:100%;min-height:60px;font-family:monospace;font-size:13px;padding:8px;border:1px solid var(--border);border-radius:4px;">${this._escapeHtml(app.ip_whitelist || '')}</textarea>
                    </div>
                    <div class="oplatform-info-item full-width">
                        <div class="oplatform-info-label">应用描述</div>
                        <div class="oplatform-info-value">${this._escapeHtml(app.app_description || '无')}</div>
                    </div>
                </div>
                <div class="oplatform-actions">
                    <button class="btn-primary btn-sm" onclick="app.openplatformSaveApp(${app.id})">💾 保存配置</button>
                    <button class="btn-secondary btn-sm" onclick="app.openplatformRegenerateSecret(${app.id})">🔄 重新生成密钥</button>
                    <button class="btn-secondary btn-sm" onclick="app.openplatformToggleApp(${app.id}, ${app.is_enabled ? 0 : 1})">${app.is_enabled ? '⏸️ 禁用' : '▶️ 启用'}</button>
                    <button class="btn-secondary btn-sm" onclick="app.openplatformShowDocs()">📖 API文档</button>
                </div>
            `;
        }
        if (this.openplatformDetailTab === 'stats') {
            return '<div class="oplatform-loading" id="oplatform-stats-container">加载统计中...</div>';
        }
        if (this.openplatformDetailTab === 'logs') {
            return '<div class="oplatform-loading" id="oplatform-logs-container">加载日志中...</div>';
        }
        return '';
    }

    async openplatformSaveApp(appId) {
        const ipWhitelist = document.getElementById('oplatform-ip-whitelist')?.value || '';
        try {
            const res = await fetch(`/api/openplatform/apps/${appId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip_whitelist: ipWhitelist })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.showNotification(this.t('openplatform.saveSuccess'), 'success');
            await this.openplatformLoadApps();
        } catch (e) {
            this.showNotification(this.t('openplatform.saveFailed', { error: e.message }), 'error');
        }
    }

    async openplatformRegenerateSecret(appId) {
        if (!confirm(this.t('error.confirmRegenerateKey'))) return;
        try {
            const res = await fetch(`/api/openplatform/apps/${appId}/regenerate`, { method: 'POST' });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            alert(this.t('openplatform.regenerateSecretMessage', { secret: data.data.app_secret }));
            await this.openplatformLoadApps();
        } catch (e) {
            this.showNotification(this.t('openplatform.saveFailed', { error: e.message }), 'error');
        }
    }

    async openplatformToggleApp(appId, enable) {
        try {
            const res = await fetch(`/api/openplatform/apps/${appId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_enabled: enable ? true : false })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.showNotification(enable ? this.t('openplatform.toggleEnabled') : this.t('openplatform.toggleDisabled'), 'success');
            await this.openplatformLoadApps();
        } catch (e) {
            this.showNotification(this.t('openplatform.saveFailed', { error: e.message }), 'error');
        }
    }

    async openplatformCreateApp() {
        const appName = prompt(this.t('openplatform.createAppPrompt'));
        if (!appName || !appName.trim()) return;
        const appDesc = prompt(this.t('openplatform.createAppDescPrompt')) || '';
        try {
            const res = await fetch('/api/openplatform/apps', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ app_name: appName.trim(), app_description: appDesc.trim() })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            alert(this.t('openplatform.createAppSuccess', { appKey: data.data.app_key, appSecret: data.data.app_secret }));
            await this.openplatformLoadApps();
        } catch (e) {
            this.showNotification(this.t('openplatform.createAppFailed', { error: e.message }), 'error');
        }
    }

    async openplatformLoadStats() {
        if (!this.openplatformCurrentAppId) return;
        try {
            const res = await fetch(`/api/openplatform/apps/${this.openplatformCurrentAppId}/stats?days=7`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            const stats = data.data;
            const container = document.getElementById('oplatform-stats-container');
            if (!container) return;

            const totalCalls = stats.daily_stats.reduce((s, d) => s + (d.cnt || 0), 0);
            const totalSuccess = stats.daily_stats.reduce((s, d) => s + (d.success || 0), 0);
            const totalError = stats.daily_stats.reduce((s, d) => s + (d.error || 0), 0);

            let html = `
                <div class="oplatform-stats-grid">
                    <div class="oplatform-stat-card">
                        <div class="stat-value">${totalCalls}</div>
                        <div class="stat-label">总调用量（近7天）</div>
                    </div>
                    <div class="oplatform-stat-card">
                        <div class="stat-value">${totalSuccess}</div>
                        <div class="stat-label">成功</div>
                    </div>
                    <div class="oplatform-stat-card">
                        <div class="stat-value">${totalError}</div>
                        <div class="stat-label">失败</div>
                    </div>
                    <div class="oplatform-stat-card">
                        <div class="stat-value">${stats.daily_stats.length}</div>
                        <div class="stat-label">活跃天数</div>
                    </div>
                </div>
                <h4 style="margin-bottom:8px;">按天统计</h4>
                <table class="oplatform-chart-table">
                    <thead><tr><th>日期</th><th>调用量</th><th>成功</th><th>失败</th></tr></thead>
                    <tbody>${stats.daily_stats.map(d => `
                        <tr>
                            <td>${d.dt}</td>
                            <td>${d.cnt}</td>
                            <td><span class="success-badge">${d.success}</span></td>
                            <td><span class="error-badge">${d.error}</span></td>
                        </tr>
                    `).join('')}</tbody>
                </table>
                <h4 style="margin:16px 0 8px;">按接口统计</h4>
                <table class="oplatform-chart-table">
                    <thead><tr><th>接口路径</th><th>调用量</th></tr></thead>
                    <tbody>${stats.path_stats.map(p => `
                        <tr><td>${this._escapeHtml(p.path)}</td><td>${p.cnt}</td></tr>
                    `).join('')}</tbody>
                </table>
            `;
            container.innerHTML = html;
        } catch (e) {
            this.showNotification(this.t('openplatform.loadStatsFailed', { error: e.message }), 'error');
        }
    }

    async openplatformLoadLogs(page) {
        if (!this.openplatformCurrentAppId) return;
        try {
            const res = await fetch(`/api/openplatform/apps/${this.openplatformCurrentAppId}/logs?page=${page}&size=20`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            const logs = data.data;
            const container = document.getElementById('oplatform-logs-container');
            if (!container) return;

            let html = `
                <table class="oplatform-chart-table">
                    <thead><tr><th>${this.t('openplatform.time')}</th><th>${this.t('openplatform.method')}</th><th>${this.t('openplatform.path')}</th><th>${this.t('openplatform.status')}</th><th>${this.t('openplatform.duration')}</th><th>${this.t('openplatform.ip')}</th><th>${this.t('openplatform.error')}</th></tr></thead>
                    <tbody>${logs.logs.map(l => `
                        <tr>
                            <td>${l.created_at || '-'}</td>
                            <td>${l.method}</td>
                            <td style="font-size:12px;">${this._escapeHtml(l.path)}</td>
                            <td>${l.status_code < 400 ? `<span class="success-badge">${l.status_code}</span>` : `<span class="error-badge">${l.status_code}</span>`}</td>
                            <td>${l.request_time}ms</td>
                            <td>${l.request_ip || '-'}</td>
                            <td style="font-size:11px;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this._escapeHtml(l.error_message || '-')}</td>
                        </tr>
                    `).join('')}</tbody>
                </table>
                <div class="oplatform-pagination">
                    <button ${page <= 1 ? 'disabled' : ''} onclick="app.openplatformLoadLogs(${page - 1})">${this.t('common.previous')}</button>
                    <span class="page-info">${this.t('openplatform.pageInfo', { page: page, totalPages: logs.total_pages, total: logs.total })}</span>
                    <button ${page >= logs.total_pages ? 'disabled' : ''} onclick="app.openplatformLoadLogs(${page + 1})">${this.t('common.next')}</button>
                </div>
            `;
            container.innerHTML = html;
        } catch (e) {
            this.showNotification(this.t('toast.loadLogsFailed', '加载日志失败') + ': ' + e.message, 'error');
        }
    }

    openplatformShowDocs() {
        const modal = document.createElement('div');
        modal.className = 'oplatform-docs-modal';
        modal.innerHTML = `
            <div class="docs-content">
                <div class="docs-header">
                    <h3>📖 ${this.t('openplatform.apiDocs')}</h3>
                    <button class="btn-secondary btn-sm" onclick="this.closest('.oplatform-docs-modal').remove()">✕ ${this.t('common.close')}</button>
                </div>
                <div class="docs-body">
                    <h4 style="margin-top:0;">1. 认证方式</h4>
                    <p style="font-size:13px;color:var(--text-secondary);">三种认证方式均使用 <code>Authorization</code> 请求头携带凭证。</p>

                    <h5>API Key（HMAC签名）</h5>
                    <div class="docs-code">Authorization: Apikey {app_key}:{signature}
X-Timestamp: {unix_timestamp}
signature = HMAC-SHA256(app_secret, method + path + body + timestamp)</div>

                    <h5>JWT（短期令牌）</h5>
                    <div class="docs-code">Authorization: Bearer {jwt_token}</div>

                    <h5>OAuth2</h5>
                    <div class="docs-code">Authorization: OAuth {access_token}</div>

                    <h4 style="margin-top:24px;">2. 接口列表</h4>

                    ${[{
                        method: 'GET', path: '/openapi/v1/qrcodes/list', desc: '分页查询二维码列表',
                        params: '?page=1&size=50&keyword=关键词&tag=标签'
                    },{
                        method: 'GET', path: '/openapi/v1/qrcodes/{id}', desc: '查询单个二维码详情'
                    },{
                        method: 'POST', path: '/openapi/v1/qrcodes/create', desc: '创建二维码',
                        body: '{"title":"标题","type":"static","content":"内容"}'
                    },{
                        method: 'GET', path: '/openapi/v1/qrcodes/{id}/data', desc: '获取二维码扫描数据（含最近扫描记录）'
                    },{
                        method: 'GET', path: '/openapi/v1/forms/{form_id}/submissions', desc: '查询表单提交记录',
                        params: '?page=1&size=50'
                    },{
                        method: 'POST', path: '/openapi/v1/forms/{form_id}/submit', desc: '提交表单数据',
                        body: '{"field1":"value1","field2":"value2"}'
                    },{
                        method: 'GET', path: '/openapi/v1/workorders/list', desc: '查询工单列表',
                        params: '?page=1&size=50&status=open'
                    },{
                        method: 'POST', path: '/openapi/v1/workorders/create', desc: '创建工单',
                        body: '{"title":"标题","description":"描述","priority":"normal"}'
                    },{
                        method: 'GET', path: '/openapi/v1/inspections/list', desc: '查询巡检记录',
                        params: '?page=1&size=50'
                    },{
                        method: 'GET', path: '/openapi/v1/stats/overview', desc: '获取概览统计数据'
                    },{
                        method: 'POST', path: '/openapi/v1/token', desc: '签发JWT令牌（需API Key认证）',
                        body: '{"expire_minutes":60}'
                    },{
                        method: 'POST', path: '/openapi/v1/token/revoke', desc: '吊销当前JWT令牌'
                    }].map(e => `
                        <div class="docs-endpoint">
                            <span class="docs-method ${e.method.toLowerCase()}">${e.method}</span>
                            <span class="docs-path">${e.path}</span>
                            <p class="docs-desc">${e.desc}</p>
                            ${e.params ? `<div class="docs-code">${e.path}${e.params}</div>` : ''}
                            ${e.body ? `<div class="docs-code">${e.body}</div>` : ''}
                        </div>
                    `).join('')}

                    <h4 style="margin-top:24px;">3. 错误码说明</h4>
                    <table class="oplatform-chart-table">
                        <thead><tr><th>状态码</th><th>说明</th></tr></thead>
                        <tbody>
                            <tr><td>200</td><td>成功</td></tr>
                            <tr><td>400</td><td>请求参数错误</td></tr>
                            <tr><td>401</td><td>认证失败（签名错误/令牌无效/过期）</td></tr>
                            <tr><td>403</td><td>IP白名单拒绝 / 应用已禁用</td></tr>
                            <tr><td>404</td><td>资源不存在</td></tr>
                            <tr><td>429</td><td>请求频率超限（含Retry-After头）</td></tr>
                            <tr><td>500</td><td>服务器内部错误</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.addEventListener('click', function(e) {
            if (e.target === modal) modal.remove();
        });
    }

    // ============ 工作流引擎 ============

    workflow = {
        workflows: [],
        currentWorkflowId: null,
        currentVersion: null,
        nodes: [],
        edges: [],
        selectedNodeId: null,
        isConnecting: false,
        connectSource: null,
        editorMode: 'edit',
        triggerTypes: {},
        actionTypes: {}
    };

    async workflowLoadList() {
        try {
            document.getElementById('workflow-list').innerHTML = '<div class="workflow-loading">' + this.t('workflow.loading') + '</div>';
            const res = await fetch('/api/workflow/definitions');
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.workflow.workflows = data.data.workflows || [];
            this.workflow.triggerTypes = data.data.trigger_types || {};
            this.workflow.actionTypes = data.data.action_types || {};
            this.workflowRenderList();
            if (this.workflow.currentWorkflowId) {
                const found = this.workflow.workflows.find(w => w.id === this.workflow.currentWorkflowId);
                if (!found) {
                    this.workflow.currentWorkflowId = null;
                    document.getElementById('workflow-right-panel').innerHTML =
                        '<div class="workflow-empty-state"><div class="workflow-empty-icon">⚡</div><p>' + this.t('workflow.selectWorkflowHint') + '</p></div>';
                }
            }
        } catch (e) {
            this.showNotification(this.t('workflow.loadingFailed', { error: e.message }), 'error');
        }
    }

    workflowRenderList() {
        const list = document.getElementById('workflow-list');
        if (!this.workflow.workflows.length) {
            list.innerHTML = '<div class="workflow-loading">' + this.t('workflow.noWorkflows') + '</div>';
            return;
        }
        list.innerHTML = this.workflow.workflows.map(w => {
            const triggerLabel = (this.workflow.triggerTypes[w.trigger_type] || {}).label || w.trigger_type;
            const enabledClass = w.is_enabled ? 'workflow-badge-enabled' : 'workflow-badge-disabled';
            return `
            <div class="workflow-item ${w.id === this.workflow.currentWorkflowId ? 'active' : ''}"
                 onclick="app.workflowSelect(${w.id})">
                <div class="workflow-item-name">${this.escapeHtml(w.name)}</div>
                <div class="workflow-item-meta">
                    <span class="workflow-item-badge ${enabledClass}">${w.is_enabled ? this.t('workflow.enabled') : this.t('workflow.disabled')}</span>
                    <span class="workflow-item-badge workflow-badge-trigger">${triggerLabel}</span>
                    <span>v${w.current_version}</span>
                </div>
            </div>`;
        }).join('');
    }

    async workflowSelect(wfId) {
        this.workflow.currentWorkflowId = wfId;
        this.workflow.selectedNodeId = null;
        this.workflowRenderList();
        const wf = this.workflow.workflows.find(w => w.id === wfId);
        if (!wf) return;
        this.workflow.currentVersion = wf.current_version;

        try {
            const res = await fetch(`/api/workflow/definitions/${wfId}/versions`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            const versions = data.data.versions || [];
            const latest = versions.find(v => v.version === wf.current_version);
            if (latest) {
                this.workflow.nodes = JSON.parse(latest.nodes_json || '[]');
                this.workflow.edges = JSON.parse(latest.edges_json || '[]');
            } else {
                this.workflow.nodes = [];
                this.workflow.edges = [];
            }
        } catch (e) {
            this.workflow.nodes = [];
            this.workflow.edges = [];
        }
        this.workflowRenderEditor(wf);
    }

    workflowRenderEditor(wf) {
        const panel = document.getElementById('workflow-right-panel');
        const triggerLabel = (this.workflow.triggerTypes[wf.trigger_type] || {}).label || wf.trigger_type;
        panel.innerHTML = `
        <div class="workflow-editor">
            <div class="workflow-editor-header">
                <h4>${this.escapeHtml(wf.name)}</h4>
                <span class="workflow-version-badge">v${this.workflow.currentVersion}</span>
                <span style="font-size:12px;color:var(--text-secondary);">触发器: ${triggerLabel}</span>
                <div class="workflow-editor-header-actions">
                    <button class="btn-outline btn-sm" onclick="app.workflowToggleEnabled(${wf.id})" style="font-size:12px;">
                        ${wf.is_enabled ? this.t('workflow.disabled') : this.t('workflow.enabled')}
                    </button>
                    <button class="btn-outline btn-sm" onclick="app.workflowExecute(${wf.id})" style="font-size:12px;">▶ ${this.t('workflow.testExecute')}</button>
                    <button class="btn-primary btn-sm" onclick="app.workflowSave()" style="font-size:12px;">${this.t('common.save')}</button>
                    <button class="btn-secondary btn-sm" onclick="app.workflowClose()" style="font-size:12px;">✕ ${this.t('common.close')}</button>
                </div>
            </div>
            <div class="workflow-editor-canvas" id="workflow-canvas">
                <div class="workflow-node-palette" id="workflow-palette">
                    <div class="palette-title">${this.t('workflow.palette')}</div>
                    <div class="palette-node" draggable="true" data-type="condition" ondragstart="app.workflowDragStart(event)">
                        <span class="palette-dot condition"></span>${this.t('workflow.nodeCondition')}
                    </div>
                    <div class="palette-node" draggable="true" data-type="action" ondragstart="app.workflowDragStart(event)">
                        <span class="palette-dot action"></span>${this.t('workflow.nodeAction')}
                    </div>
                    <div class="palette-node" draggable="true" data-type="loop" ondragstart="app.workflowDragStart(event)">
                        <span class="palette-dot loop"></span>${this.t('workflow.nodeLoop')}
                    </div>
                    <div class="palette-node" draggable="true" data-type="parallel" ondragstart="app.workflowDragStart(event)">
                        <span class="palette-dot parallel"></span>${this.t('workflow.nodeParallel')}
                    </div>
                </div>
                <svg class="workflow-editor-svg" id="workflow-svg">
                    <defs>
                        <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                            <polygon points="0 0, 10 3.5, 0 7" fill="#94A3B8"/>
                        </marker>
                        <marker id="arrowhead-green" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                            <polygon points="0 0, 10 3.5, 0 7" fill="#22C55E"/>
                        </marker>
                        <marker id="arrowhead-red" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                            <polygon points="0 0, 10 3.5, 0 7" fill="#EF4444"/>
                        </marker>
                    </defs>
                    <g id="wf-edges-group"></g>
                    <g id="wf-nodes-group"></g>
                </svg>
                <div id="workflow-config-panel" style="display:none;"></div>
            </div>
        </div>`;

        const canvas = document.getElementById('workflow-canvas');
        canvas.addEventListener('dragover', (e) => { e.preventDefault(); });
        canvas.addEventListener('drop', (e) => { this.workflowDropNode(e); });

        this.workflowRenderSvg();
    }

    workflowRenderSvg() {
        const edgesGroup = document.getElementById('wf-edges-group');
        const nodesGroup = document.getElementById('wf-nodes-group');
        if (!edgesGroup || !nodesGroup) return;

        // 渲染连线
        edgesGroup.innerHTML = this.workflow.edges.map(e => {
            const srcNode = this.workflow.nodes.find(n => n.id === e.source);
            const tgtNode = this.workflow.nodes.find(n => n.id === e.target);
            if (!srcNode || !tgtNode) return '';
            const sx = srcNode.x + 70;
            const sy = srcNode.y + 20;
            const tx = tgtNode.x;
            const ty = tgtNode.y + 20;
            const midX = (sx + tx) / 2;
            let cssClass = 'wf-edge';
            let marker = 'url(#arrowhead)';
            if (e.label === 'true') { cssClass += ' true-branch'; marker = 'url(#arrowhead-green)'; }
            if (e.label === 'false') { cssClass += ' false-branch'; marker = 'url(#arrowhead-red)'; }
            const labelX = midX, labelY = sy - 6;
            return `
            <g>
                <path d="M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}" class="${cssClass}" marker-end="${marker}"/>
                ${e.label ? `<text x="${labelX}" y="${labelY}" text-anchor="middle" font-size="10" fill="#64748B">${e.label}</text>` : ''}
            </g>`;
        }).join('');

        // 渲染节点
        nodesGroup.innerHTML = this.workflow.nodes.map(n => {
            const typeClass = n.type === 'trigger' ? 'trigger' : n.type === 'condition' ? 'condition' :
                              n.type === 'loop' ? 'loop' : n.type === 'parallel' ? 'parallel' : 'action';
            const selected = n.id === this.workflow.selectedNodeId ? ' selected' : '';
            const typeLabels = { trigger: this.t('workflow.triggerType'), condition: this.t('workflow.nodeCondition'), action: this.t('workflow.nodeAction'), loop: this.t('workflow.nodeLoop'), parallel: this.t('workflow.nodeParallel') };
            const label = n.label || (typeLabels[n.type] || n.type);
            const subtitle = n.config && n.config.action_type ? this.workflow.actionTypes[n.config.action_type]?.label || '' : '';
            const subtitleY = subtitle ? 32 : 0;
            return `
            <g class="wf-node ${typeClass}${selected}" transform="translate(${n.x},${n.y})"
               onclick="app.workflowSelectNode('${n.id}')" data-node-id="${n.id}">
                <rect width="140" height="40" rx="8" ry="8"/>
                <text x="70" y="17">${label}</text>
                ${subtitle ? `<text x="70" y="32" class="node-subtitle">${subtitle}</text>` : ''}
            </g>`;
        }).join('');

        // 只保留 trigger 节点的 type 属性
        this.workflow.nodes.forEach(n => {
            const g = document.querySelector(`.wf-node[data-node-id="${n.id}"]`);
            if (g) {
                g.addEventListener('mousedown', (e) => { if (e.shiftKey) { this.workflow.startConnection(n.id); } });
            }
        });
    }

    workflowDragStart(e) {
        e.dataTransfer.setData('text/plain', e.target.closest('.palette-node').dataset.type);
    }

    workflowDropNode(e) {
        e.preventDefault();
        const nodeType = e.dataTransfer.getData('text/plain');
        if (!nodeType) return;
        const canvas = document.getElementById('workflow-canvas');
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left + canvas.scrollLeft - 70;
        const y = e.clientY - rect.top + canvas.scrollTop - 20;
        const newNode = {
            id: 'node_' + Date.now(),
            type: nodeType,
            label: nodeType === 'condition' ? this.t('workflow.nodeCondition') : nodeType === 'loop' ? this.t('workflow.nodeLoop') : nodeType === 'parallel' ? this.t('workflow.nodeParallel') : this.t('workflow.nodeAction'),
            x: Math.max(10, x),
            y: Math.max(10, y),
            config: {},
            max_retries: 3
        };
        this.workflow.nodes.push(newNode);
        this.workflow.selectedNodeId = newNode.id;
        this.workflowRenderSvg();
        this.workflowShowConfig(newNode);
    }

    workflowSelectNode(nodeId) {
        this.workflow.selectedNodeId = nodeId;
        this.workflowRenderSvg();
        const node = this.workflow.nodes.find(n => n.id === nodeId);
        if (node) this.workflowShowConfig(node);
    }

    workflowStartConnection(sourceId) {
        this.workflow.isConnecting = true;
        this.workflow.connectSource = sourceId;
        this.showNotification(this.t('workflow.connectHint'), 'info');
        const nodesGroup = document.getElementById('wf-nodes-group');
        if (nodesGroup) {
            nodesGroup.style.cursor = 'crosshair';
            const handler = (e) => {
                const g = e.target.closest('.wf-node');
                if (g) {
                    const targetId = g.dataset.nodeId;
                    if (targetId && targetId !== sourceId) {
                        const existing = this.workflow.edges.find(ed => ed.source === sourceId && ed.target === targetId);
                        if (!existing) {
                            let label = '';
                            const srcNode = this.workflow.nodes.find(n => n.id === sourceId);
                            if (srcNode && srcNode.type === 'condition') {
                                label = prompt(this.t('workflow.lineLabelPrompt'), 'true') || '';
                            }
                            this.workflow.edges.push({ source: sourceId, target: targetId, label: label });
                            this.workflowRenderSvg();
                        }
                    }
                }
                this.workflow.isConnecting = false;
                this.workflow.connectSource = null;
                nodesGroup.style.cursor = '';
                nodesGroup.removeEventListener('click', handler);
            };
            nodesGroup.addEventListener('click', handler);
        }
    }

    workflowShowConfig(node) {
        const panel = document.getElementById('workflow-config-panel');
        if (!panel) return;
        panel.style.display = 'flex';

        let bodyHtml = '';
        if (node.type === 'action') {
            const actionOptions = Object.entries(this.workflow.actionTypes).map(([k, v]) =>
                `<option value="${k}" ${node.config.action_type === k ? 'selected' : ''}>${v.label}</option>`
            ).join('');
            bodyHtml = `
            <div class="config-group">
                <label>${this.t('workflow.nodeAction')}</label>
                <select onchange="app.workflowUpdateConfig('${node.id}', 'action_type', this.value)">${actionOptions}</select>
            </div>
            <div class="config-group">
                <label>${this.t('workflow.configParams')}</label>
                <textarea onchange="app.workflowUpdateConfig('${node.id}', 'params', this.value)"
                          rows="6">${JSON.stringify(node.config.params || {}, null, 2)}</textarea>
            </div>`;
        } else if (node.type === 'condition') {
            const conditions = node.config.conditions || { logic: 'AND', conditions: [] };
            bodyHtml = `
            <div class="config-group">
                <label>${this.t('workflow.conditionLogic')}</label>
                <select onchange="app.workflowUpdateConditionLogic('${node.id}', this.value)">
                    <option value="AND" ${conditions.logic === 'AND' ? 'selected' : ''}>所有条件都满足 (AND)</option>
                    <option value="OR" ${conditions.logic === 'OR' ? 'selected' : ''}>任一条件满足 (OR)</option>
                </select>
            </div>
            <div class="config-group">
                <label>${this.t('workflow.conditionList')}</label>
                ${(conditions.conditions || []).map((c, i) => `
                <div class="condition-row">
                    <input class="field-col" placeholder="${this.t('workflow.fieldPath')}" value="${c.field || ''}"
                           onchange="app.workflowUpdateConditionItem('${node.id}', ${i}, 'field', this.value)">
                    <select class="op-col" onchange="app.workflowUpdateConditionItem('${node.id}', ${i}, 'operator', this.value)">
                        ${['gt','gte','lt','lte','eq','neq','contains','not_contains','starts_with','is_empty','is_not_empty'].map(op =>
                            `<option value="${op}" ${c.operator === op ? 'selected' : ''}>${op}</option>`
                        ).join('')}
                    </select>
                    <input class="val-col" placeholder="${this.t('workflow.compareValue')}" value="${c.value || ''}"
                           onchange="app.workflowUpdateConditionItem('${node.id}', ${i}, 'value', this.value)">
                </div>`).join('')}
                <button class="btn-outline btn-sm" style="margin-top:4px;font-size:11px;"
                        onclick="app.workflowAddCondition('${node.id}')">+ ${this.t('workflow.addCondition')}</button>
            </div>`;
        } else if (node.type === 'loop') {
            bodyHtml = `
            <div class="config-group">
                <label>${this.t('workflow.itemsField')}</label>
                <input value="${node.config.items_field || ''}" placeholder="${this.t('workflow.itemsFieldPlaceholder')}"
                       onchange="app.workflowUpdateConfig('${node.id}', 'items_field', this.value)">
            </div>`;
        } else if (node.type === 'parallel') {
            bodyHtml = `
            <div class="config-group">
                <label>${this.t('workflow.parallelNode')}</label>
                <p style="font-size:12px;color:var(--text-secondary);">${this.t('workflow.parallelHint')}</p>
            </div>`;
        } else if (node.type === 'trigger') {
            bodyHtml = `
            <div class="config-group">
                <label>${this.t('workflow.triggerType')}</label>
                <p style="font-size:12px;color:var(--text-secondary);">${this.t('workflow.triggerHint')}</p>
            </div>`;
        }

        bodyHtml += `
        <div class="config-group">
            <label>${this.t('workflow.nodeLabel')}</label>
            <input value="${node.label || ''}" onchange="app.workflowUpdateConfig('${node.id}', 'label', this.value)">
        </div>
        <div class="config-group">
            <label>${this.t('workflow.maxRetries')}</label>
            <input type="number" value="${node.max_retries || 3}" min="0" max="10"
                   onchange="app.workflowUpdateConfig('${node.id}', 'max_retries', parseInt(this.value))">
        </div>`;

        panel.innerHTML = `
        <div class="workflow-config-panel-header">
            <h4>${node.label || node.type}</h4>
            <div style="display:flex;gap:6px;">
                <button class="btn-outline btn-sm" style="font-size:11px;color:#EF4444;border-color:#EF4444;"
                        onclick="app.workflowDeleteNode('${node.id}')">${this.t('common.delete')}</button>
                <button class="btn-secondary btn-sm" onclick="app.workflowCloseConfig()">✕</button>
            </div>
        </div>
        <div class="workflow-config-panel-body">${bodyHtml}</div>
        <div class="workflow-config-panel-footer">
            <button class="btn-primary btn-sm" onclick="app.workflowCloseConfig()">${this.t('common.confirm')}</button>
        </div>`;
    }

    workflowUpdateConfig(nodeId, key, value) {
        const node = this.workflow.nodes.find(n => n.id === nodeId);
        if (!node) return;
        if (key === 'params') {
            try { node.config.params = JSON.parse(value); } catch (e) { /* keep old */ }
        } else if (key === 'action_type') {
            node.config.action_type = value;
            node.config.params = {};
        } else {
            node.config[key] = value;
        }
        this.workflowRenderSvg();
    }

    workflowUpdateConditionLogic(nodeId, value) {
        const node = this.workflow.nodes.find(n => n.id === nodeId);
        if (!node) return;
        if (!node.config.conditions) node.config.conditions = { logic: 'AND', conditions: [] };
        node.config.conditions.logic = value;
    }

    workflowUpdateConditionItem(nodeId, index, key, value) {
        const node = this.workflow.nodes.find(n => n.id === nodeId);
        if (!node) return;
        if (!node.config.conditions) node.config.conditions = { logic: 'AND', conditions: [] };
        if (!node.config.conditions.conditions[index]) node.config.conditions.conditions[index] = {};
        node.config.conditions.conditions[index][key] = value;
    }

    workflowAddCondition(nodeId) {
        const node = this.workflow.nodes.find(n => n.id === nodeId);
        if (!node) return;
        if (!node.config.conditions) node.config.conditions = { logic: 'AND', conditions: [] };
        node.config.conditions.conditions.push({ field: '', operator: 'eq', value: '' });
        this.workflowShowConfig(node);
    }

    workflowDeleteNode(nodeId) {
        this.workflow.nodes = this.workflow.nodes.filter(n => n.id !== nodeId);
        this.workflow.edges = this.workflow.edges.filter(e => e.source !== nodeId && e.target !== nodeId);
        this.workflow.selectedNodeId = null;
        this.workflowRenderSvg();
        this.workflowCloseConfig();
    }

    workflowCloseConfig() {
        const panel = document.getElementById('workflow-config-panel');
        if (panel) panel.style.display = 'none';
    }

    async workflowSave() {
        if (!this.workflow.currentWorkflowId) return;
        try {
            const res = await fetch(`/api/workflow/definitions/${this.workflow.currentWorkflowId}/versions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nodes: this.workflow.nodes, edges: this.workflow.edges })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.showNotification(this.t('workflow.saveSuccess', { version: data.data.version }), 'success');
            this.workflow.currentVersion = data.data.version;
            await this.workflowLoadList();
        } catch (e) {
            this.showNotification(this.t('workflow.saveFailed', { error: e.message }), 'error');
        }
    }

    async workflowExecute(wfId) {
        try {
            const res = await fetch(`/api/workflow/definitions/${wfId}/execute`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ trigger_event: {} })
            });
            const data = await res.json();
            if (data.success) {
                this.showNotification(this.t('workflow.executeSuccess', { instanceId: data.instance_id }), 'success');
            } else {
                this.showNotification(this.t('workflow.executeFailed', { error: data.error || this.t('common.error') }), 'error');
            }
        } catch (e) {
            this.showNotification(this.t('workflow.executeFailed', { error: e.message }), 'error');
        }
    }

    async workflowToggleEnabled(wfId) {
        const wf = this.workflow.workflows.find(w => w.id === wfId);
        if (!wf) return;
        try {
            const res = await fetch(`/api/workflow/definitions/${wfId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_enabled: !wf.is_enabled })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            await this.workflowLoadList();
            this.showNotification(wf.is_enabled ? this.t('workflow.toggleDisabled') : this.t('workflow.toggleEnabled'), 'success');
        } catch (e) {
            this.showNotification(this.t('workflow.toggleFailed', { error: e.message }), 'error');
        }
    }

    async workflowCreate() {
        const name = prompt(this.t('workflow.createPrompt'));
        if (!name || !name.trim()) return;
        const triggerKeys = Object.keys(this.workflow.triggerTypes);
        const triggerList = triggerKeys.map(k => `${k} - ${this.workflow.triggerTypes[k].label}`).join('\n');
        const triggerType = prompt(this.t('workflow.createTriggerPrompt', { triggerList: triggerList }));
        if (!triggerType || !triggerKeys.includes(triggerType.trim())) {
            alert(this.t('workflow.invalidTriggerType'));
            return;
        }
        try {
            const res = await fetch('/api/workflow/definitions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name.trim(), trigger_type: triggerType.trim() })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            await this.workflowLoadList();
            this.workflowSelect(data.data.id);
        } catch (e) {
            this.showNotification(this.t('workflow.createFailed', { error: e.message }), 'error');
        }
    }

    workflowClose() {
        this.workflow.currentWorkflowId = null;
        this.workflow.selectedNodeId = null;
        this.workflow.nodes = [];
        this.workflow.edges = [];
        document.getElementById('workflow-right-panel').innerHTML =
            '<div class="workflow-empty-state"><div class="workflow-empty-icon">⚡</div><p>' + this.t('workflow.selectWorkflowHint') + '</p></div>';
        this.workflowRenderList();
    }

    async workflowShowHistory() {
        try {
            let wfFilter = '';
            if (this.workflow.currentWorkflowId) wfFilter = '&workflow_id=' + this.workflow.currentWorkflowId;
            const res = await fetch('/api/workflow/instances?size=200' + wfFilter);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            const instances = data.data.instances || [];

            const statusLabels = { running: this.t('workflow.statusRunning'), completed: this.t('workflow.statusCompleted'), failed: this.t('workflow.statusFailed') };
            const statusClasses = { running: 'workflow-status-running', completed: 'workflow-status-completed', failed: 'workflow-status-failed' };

            const modal = document.createElement('div');
            modal.className = 'workflow-history-modal';
            modal.innerHTML = `
            <div class="workflow-history-content">
                <div class="workflow-history-header">
                    <h3>${this.t('workflow.historyTitle')}</h3>
                    <button class="btn-secondary btn-sm" onclick="this.closest('.workflow-history-modal').remove()">✕ ${this.t('common.close')}</button>
                </div>
                <div class="workflow-history-body">
                    <table class="workflow-history-table">
                        <thead><tr>
                            <th>ID</th><th>工作流</th><th>版本</th><th>状态</th><th>开始时间</th><th>完成时间</th><th>操作</th>
                        </tr></thead>
                        <tbody>
                            ${instances.map(inst => `
                            <tr>
                                <td>${inst.id}</td>
                                <td>${inst.workflow_name || '-'}</td>
                                <td>v${inst.workflow_version}</td>
                                <td><span class="workflow-status-badge ${statusClasses[inst.status] || ''}">${statusLabels[inst.status] || inst.status}</span></td>
                                <td style="font-size:12px;">${inst.started_at || '-'}</td>
                                <td style="font-size:12px;">${inst.finished_at || '-'}</td>
                                <td><button class="btn-outline btn-sm" style="font-size:11px;" onclick="app.workflowViewLogs(${inst.id})">${this.t('workflow.viewLogs')}</button></td>
                            </tr>`).join('')}
                        </tbody>
                    </table>
                    ${instances.length === 0 ? '<p style="text-align:center;color:var(--text-secondary);padding:20px;">暂无执行记录</p>' : ''}
                </div>
            </div>`;
            document.body.appendChild(modal);
            modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });
        } catch (e) {
            this.showNotification(this.t('workflow.loadHistoryFailed', { error: e.message }), 'error');
        }
    }

    async workflowViewLogs(instanceId) {
        try {
            const res = await fetch(`/api/workflow/instances/${instanceId}/logs`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            const logs = data.data.logs || [];
            const statusLabels = { running: this.t('workflow.statusRunning'), success: this.t('workflow.statusSuccess'), failed: this.t('workflow.statusFailed'), pending: this.t('workflow.statusPending') };

            const modal = document.createElement('div');
            modal.className = 'workflow-history-modal';
            modal.innerHTML = `
            <div class="workflow-history-content" style="max-width:700px;">
                <div class="workflow-history-header">
                    <h3>${this.t('workflow.logTitle', { instanceId: instanceId })}</h3>
                    <button class="btn-secondary btn-sm" onclick="this.closest('.workflow-history-modal').remove()">✕ ${this.t('common.close')}</button>
                </div>
                <div class="workflow-history-body">
                    ${logs.map(log => `
                    <div class="workflow-log-node ${log.status}">
                        <span class="log-node-type">${log.node_type}</span>
                        <span class="log-node-label">${log.node_label || log.node_id}</span>
                        <span class="log-node-status">${statusLabels[log.status] || log.status}</span>
                        ${log.status === 'failed' ? `<div class="log-node-error">${log.error_message || ''}</div>` : ''}
                    </div>`).join('')}
                    ${logs.length === 0 ? '<p style="text-align:center;color:var(--text-secondary);">' + this.t('workflow.noLogs') + '</p>' : ''}
                </div>
            </div>`;
            document.body.appendChild(modal);
            modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });
        } catch (e) {
            this.showNotification(this.t('workflow.loadLogsFailed', { error: e.message }), 'error');
        }
    }

    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ============ 订阅制商业系统 ============

    subscriptionPlans = [];
    subscriptionCurrent = null;

    async subscriptionLoad() {
        try {
            await this.subscriptionLoadCurrent();
            await this.subscriptionLoadPlans();
            await this.subscriptionLoadBilling();
        } catch (e) {
            this.showNotification(this.t('toast.loadPlansFailed', '加载套餐信息失败') + ': ' + e.message, 'error');
        }
    }

    async subscriptionLoadCurrent() {
        try {
            const res = await fetch('/api/subscription/my');
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.subscriptionCurrent = data.subscription;
            this.subscriptionRenderCurrent();
            this.subscriptionLoadQuotas();
        } catch (e) {
            document.getElementById('sub-current-card').innerHTML = '<div class="sub-loading">加载失败</div>';
        }
    }

    async subscriptionLoadQuotas() {
        try {
            const res = await fetch('/api/subscription/quota-usage');
            const data = await res.json();
            if (!data.success || !data.quotas) return;
            this.subscriptionRenderQuotas(data.quotas);
        } catch (e) {
            console.error('配额加载失败:', e);
            const el = document.getElementById('quota-container');
            if (el) {
                el.innerHTML =
                    `<div style="color:var(--danger);
                     font-size:13px;padding:12px;">
                     ${this.t('toast.loadFailed', '加载失败，请刷新重试')}
                    </div>`;
            }
        }
    }

    subscriptionRenderCurrent() {
        const card = document.getElementById('sub-current-card');
        const sub = this.subscriptionCurrent;
        if (!sub) {
            card.innerHTML = '<div class="sub-loading">' + this.t('subscription.noSubscription') + '</div>';
            return;
        }
        const statusLabels = { active: this.t('subscription.statusActive'), trial: this.t('subscription.statusTrial'), expiring: this.t('subscription.statusExpiring'), expired: this.t('subscription.statusExpired'), cancelled: this.t('subscription.statusCancelled') };
        const endDate = sub.end_date ? sub.end_date.split(' ')[0] : '--';
        card.innerHTML = `
            <div class="sub-current-header">
                <div>
                    <span class="sub-plan-badge ${sub.plan_key}">${sub.plan_name}</span>
                    <span class="sub-status-badge ${sub.status}">${statusLabels[sub.status] || sub.status}</span>
                </div>
                <div class="sub-current-actions">
                    ${sub.status !== 'cancelled' ? '<button class="btn-secondary btn-sm" onclick="app.subscriptionCancel()">' + this.t('subscription.cancel') + '</button>' : ''}
                    <button class="btn-outline btn-sm" onclick="app.subscriptionToggleAutoRenew()">${sub.auto_renew ? this.t('subscription.autoRenewOn') : this.t('subscription.autoRenewOff')}</button>
                </div>
            </div>
            <div class="sub-current-info">
                <div class="sub-info-item">
                    <span class="sub-info-label">${this.t('subscription.startDate')}</span>
                    <span class="sub-info-value">${(sub.start_date || '').split(' ')[0]}</span>
                </div>
                <div class="sub-info-item">
                    <span class="sub-info-label">${this.t('subscription.endDate')}</span>
                    <span class="sub-info-value">${endDate}</span>
                </div>
                <div class="sub-info-item">
                    <span class="sub-info-label">${this.t('subscription.monthlyPrice')}</span>
                    <span class="sub-info-value">${sub.monthly_price > 0 ? '¥' + sub.monthly_price + this.t('subscription.month') : this.t('subscription.freePlan')}</span>
                </div>
                <div class="sub-info-item">
                    <span class="sub-info-label">${this.t('subscription.yearlyPrice')}</span>
                    <span class="sub-info-value">${sub.yearly_price > 0 ? '¥' + sub.yearly_price + this.t('subscription.year') : this.t('subscription.freePlan')}</span>
                </div>
            </div>
            <div class="sub-quota-section" id="sub-quota-section">
                <div class="sub-quota-title">${this.t('subscription.quotaUsageTitle')}</div>
                <div class="sub-loading">${this.t('common.loading')}</div>
            </div>
        `;
    }

    subscriptionRenderQuotas(quotas) {
        const section = document.getElementById('sub-quota-section');
        if (!section) return;
        const names = {
            max_qrcodes: this.t('subscription.qrcodes'), max_users: this.t('subscription.users'), max_storage_mb: this.t('subscription.storage') + '(MB)',
            max_forms: this.t('subscription.forms'), max_workorders: this.t('subscription.workorders'), max_inspections: this.t('subscription.inspections')
        };
        let html = '<div class="sub-quota-title">' + this.t('subscription.quotaUsageTitle') + '</div><div class="sub-quota-grid">';
        for (const [key, val] of Object.entries(quotas)) {
            const limit = val.limit;
            const used = val.used;
            const pct = limit === -1 ? 0 : limit === 0 ? 100 : Math.min(100, Math.round((used / limit) * 100));
            const barClass = pct >= 90 ? 'danger' : pct >= 70 ? 'warning' : '';
            const limitText = limit === -1 ? this.t('subscription.unlimited') : limit;
            html += `
                <div class="sub-quota-item">
                    <div class="sub-quota-name">${names[key] || key}</div>
                    <div class="sub-quota-bar-wrap"><div class="sub-quota-bar ${barClass}" style="width:${pct}%"></div></div>
                    <div class="sub-quota-text">${used} / ${limitText}</div>
                </div>`;
        }
        html += '</div>';
        section.innerHTML = html;
    }

    async subscriptionLoadPlans() {
        try {
            const res = await fetch('/api/subscription/plans');
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.subscriptionPlans = data.plans;
            this.subscriptionRenderPlans();
        } catch (e) {
            document.getElementById('sub-plans-grid').innerHTML = '<div class="sub-loading">' + this.t('subscription.loadFailed') + '</div>';
        }
    }

    subscriptionRenderPlans() {
        const grid = document.getElementById('sub-plans-grid');
        const currentKey = this.subscriptionCurrent ? this.subscriptionCurrent.plan_key : null;
        const featureLabels = {
            workflow: this.t('workflow.title'), openapi: this.t('openplatform.title'), file_upload: this.t('common.upload'),
            export: this.t('common.export'), custom_domain: 'Custom Domain', priority_support: 'Priority Support'
        };
        grid.innerHTML = this.subscriptionPlans.map(plan => {
            const isCurrent = plan.plan_key === currentKey;
            const features = plan.features || {};
            const featureHtml = Object.entries(featureLabels).map(([k, label]) => {
                const enabled = features[k];
                return `<li><span class="${enabled ? 'feat-check' : 'feat-cross'}">${enabled ? '✓' : '✕'}</span> ${label}</li>`;
            }).join('');
            const monthlyPrice = plan.monthly_price > 0 ? '¥' + plan.monthly_price : '免费';
            const btnHtml = isCurrent
                ? '<button class="plan-btn btn-current">' + this.t('subscription.currentPlan') + '</button>'
                : '<button class="plan-btn btn-primary" onclick="app.subscriptionSubscribe(\'' + plan.plan_key + '\')">' + this.t('subscription.subscribe') + '</button>';
            return `
                <div class="sub-plan-card ${isCurrent ? 'current' : ''}">
                    <div class="plan-header">
                        <div class="plan-name">${plan.name}</div>
                        <div class="plan-price">
                            <div class="amount">${monthlyPrice}</div>
                            <div class="period">${this.t('subscription.perMonth')}</div>
                        </div>
                    </div>
                    <div class="plan-desc">${plan.description}</div>
                    <ul class="plan-features">${featureHtml}</ul>
                    ${btnHtml}
                </div>`;
        }).join('');
    }

    async subscriptionSubscribe(planKey) {
        const billingCycle = confirm(this.t('error.billingCyclePrompt')) ? 'yearly' : 'monthly';
        try {
            const res = await fetch('/api/subscription/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ plan_key: planKey, billing_cycle: billingCycle })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            if (data.pay_url) {
                const txnId = data.txn_id;
                if (confirm(this.t('subscription.confirmSimulatePayment', { txnId: txnId }))) {
                    const payRes = await fetch('/api/subscription/confirm-payment', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ txn_id: txnId })
                    });
                    const payData = await payRes.json();
                    if (!payData.success) throw new Error(payData.error);
                    this.showNotification(this.t('subscription.subscribeSuccess'), 'success');
                    this.subscriptionLoad();
                }
            } else {
                this.showNotification(data.message || this.t('toast.operationSuccess', '操作成功'), 'success');
                this.subscriptionLoad();
            }
        } catch (e) {
            this.showNotification(this.t('subscription.subscribeFailed', { error: e.message }), 'error');
        }
    }

    async subscriptionCancel() {
        const reason = prompt(this.t('subscription.cancelReasonPrompt')) || '';
        try {
            const res = await fetch('/api/subscription/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: reason })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.showNotification(this.t('subscription.cancelSuccess'), 'success');
            this.subscriptionLoad();
        } catch (e) {
            this.showNotification(this.t('subscription.cancelFailed', { error: e.message }), 'error');
        }
    }

    async subscriptionToggleAutoRenew() {
        try {
            const newVal = !(this.subscriptionCurrent && this.subscriptionCurrent.auto_renew);
            const res = await fetch('/api/subscription/auto-renew', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ auto_renew: newVal })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.showNotification(newVal ? this.t('subscription.renewOn') : this.t('subscription.renewOff'), 'success');
            this.subscriptionLoad();
        } catch (e) {
            this.showNotification(this.t('subscription.toggleRenewFailed', { error: e.message }), 'error');
        }
    }

    async subscriptionLoadBilling() {
        try {
            const res = await fetch('/api/subscription/billing-history');
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            const tbody = document.getElementById('sub-billing-tbody');
            if (!data.invoices || data.invoices.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="sub-loading">' + this.t('subscription.billingEmpty') + '</td></tr>';
                return;
            }
            const typeLabels = { new_subscription: this.t('subscription.newSubscription'), renewal: this.t('subscription.renewal'), upgrade: this.t('subscription.upgrade'), downgrade: this.t('subscription.downgrade'), refund: this.t('subscription.refund') };
            const statusLabels = { paid: this.t('subscription.paid'), pending: this.t('subscription.pending'), refunded: this.t('subscription.refunded'), cancelled: this.t('subscription.cancelled') };
            tbody.innerHTML = data.invoices.map(inv => `
                <tr>
                    <td>${(inv.created_at || '').split(' ')[0]}</td>
                    <td>${inv.plan_name || '--'}</td>
                    <td>¥${inv.amount.toFixed(2)}</td>
                    <td>${typeLabels[inv.invoice_type] || inv.invoice_type}</td>
                    <td class="invoice-status-${inv.status}">${statusLabels[inv.status] || inv.status}</td>
                </tr>`).join('');
        } catch (e) {
            document.getElementById('sub-billing-tbody').innerHTML = '<tr><td colspan="5" class="sub-loading">' + this.t('subscription.loadFailed') + '</td></tr>';
        }
    }

    // ============ 运营收入统计面板 ============

    async revenueLoad() {
        try {
            const res = await fetch('/api/admin/revenue/summary');
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            this.revenueRender(data);
        } catch (e) {
            this.showNotification(this.t('revenue.loadFailed', { error: e.message }), 'error');
        }
    }

    revenueRender(data) {
        const container = document.getElementById('revenue-dashboard');
        if (!container) return;
        container.innerHTML = `
            <div class="revenue-header">
                <h2>${this.t('revenue.dashboardTitle')}</h2>
            </div>
            <div class="revenue-stats-grid">
                <div class="revenue-stat-card">
                    <div class="stat-label">${this.t('revenue.totalPaid')}</div>
                    <div class="stat-value">${data.total_paid}</div>
                </div>
                <div class="revenue-stat-card">
                    <div class="stat-label">${this.t('revenue.totalRevenue')}</div>
                    <div class="stat-value revenue">¥${data.total_revenue.toFixed(2)}</div>
                </div>
                <div class="revenue-stat-card">
                    <div class="stat-label">${this.t('revenue.revenue30d')}</div>
                    <div class="stat-value revenue">¥${data.revenue_30d.toFixed(2)}</div>
                </div>
                <div class="revenue-stat-card">
                    <div class="stat-label">${this.t('revenue.activeSubs')}</div>
                    <div class="stat-value">${data.active_subscriptions}</div>
                </div>
            </div>
            <div class="revenue-section">
                <h3>${this.t('revenue.byPlan')}</h3>
                <table class="revenue-table">
                    <thead><tr><th>套餐</th><th>付费订单数</th><th>收入</th></tr></thead>
                    <tbody>
                        ${(data.by_plan || []).map(p => `
                        <tr>
                            <td>${p.name}</td>
                            <td>${p.cnt}</td>
                            <td>¥${(p.revenue || 0).toFixed(2)}</td>
                        </tr>`).join('')}
                        ${(data.by_plan || []).length === 0 ? '<tr><td colspan="3" class="sub-loading">' + this.t('revenue.emptyState') + '</td></tr>' : ''}
                    </tbody>
                </table>
            </div>
            <div class="revenue-section">
                <h3>${this.t('revenue.dailyTrend')}</h3>
                <div class="revenue-chart-bar" id="revenue-chart">
                    ${(data.daily_trend || []).length === 0 ? '<div class="sub-loading">' + this.t('revenue.emptyState') + '</div>' : ''}
                </div>
            </div>
        `;
        if (data.daily_trend && data.daily_trend.length > 0) {
            const chart = document.getElementById('revenue-chart');
            const maxRev = Math.max(...data.daily_trend.map(d => d.revenue || 0), 1);
            data.daily_trend.forEach(d => {
                const height = Math.max(4, ((d.revenue || 0) / maxRev) * 100);
                const bar = document.createElement('div');
                bar.className = 'revenue-bar-item';
                bar.style.height = height + 'px';
                bar.title = d.day + ': ¥' + (d.revenue || 0).toFixed(2);
                chart.appendChild(bar);
            });
        }
    }
initTheme() {
        const saved = localStorage.getItem('theme') || 'light';
        this.currentTheme = saved;
        document.documentElement.setAttribute(
            'data-theme', saved);
    }

    applyTheme(theme) {
        document.documentElement.setAttribute(
            'data-theme', theme);
        localStorage.setItem('theme', theme);
        this.currentTheme = theme;
    }

    toggleTheme() {
        const next = this.currentTheme === 'light'
            ? 'dark' : 'light';
        this.applyTheme(next);
    }

    isEditMode = false;
    currentLayout = [];
    wsModuleNames = {
      pending_tasks: '待处理事项',
      today_stats: '快捷操作',
      trend_chart: '趋势图表',
      ranking: '排行榜',
      quick_actions: '快捷入口',
      recent_activities: '最近活动'
    };

    async loadWorkspaceLayout() {
      try {
        const res = await fetch('/api/workspace/layout');
        const data = await res.json();
        if (!data.success) return;
        this.currentLayout = data.layout;
        if (data.theme) this.applyTheme(data.theme);
        this.renderAllModules(data.layout);
      } catch(e) {
        console.error('加载布局失败', e);
      }
    }

    renderAllModules(layout) {
      const sorted = [...layout].sort(
        (a, b) => a.order - b.order);
      const container = document.getElementById(
        'ws-modules-container');
      if (!container) return;
      container.innerHTML = '';
      sorted.forEach(item => {
        const el = document.createElement('div');
        el.className = 'ws-module';
        el.dataset.moduleId = item.module_id;
        if (!item.visible) el.classList.add('hidden');
        el.innerHTML = this.getModuleHTML(item.module_id);
        container.appendChild(el);
      });
      this.renderHiddenBar();
    }

    getModuleHTML(id) {
      const titles = this.wsModuleNames;
      const maps = {
        today_stats: `
      <div class="ws-section-title">快捷操作</div>
      <div class="ws-quick-cards">
        <button class="ws-quick-card" onclick="app.switchTab('generator');setTimeout(()=>{const b=document.querySelector('.type-btn[data-type=url]');if(b)b.click()},200)" tabindex="0">
          <div class="ws-quick-card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
          </div>
          <span class="ws-quick-card-label">网站</span>
        </button>
        <button class="ws-quick-card" onclick="app.switchTab('generator');setTimeout(()=>{const b=document.querySelector('.type-btn[data-type=file]');if(b)b.click()},200)" tabindex="0">
          <div class="ws-quick-card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          </div>
          <span class="ws-quick-card-label">文件</span>
        </button>
        <button class="ws-quick-card" onclick="app.switchTab('generator');setTimeout(()=>{const b=document.querySelector('.type-btn[data-type=image]');if(b)b.click()},200)" tabindex="0">
          <div class="ws-quick-card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          </div>
          <span class="ws-quick-card-label">图片</span>
        </button>
        <button class="ws-quick-card" onclick="app.switchTab('generator');setTimeout(()=>{const b=document.querySelector('.type-btn[data-type=media]');if(b)b.click()},200)" tabindex="0">
          <div class="ws-quick-card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
          </div>
          <span class="ws-quick-card-label">视频</span>
        </button>
        <button class="ws-quick-card" onclick="app.switchTab('generator');setTimeout(()=>{const b=document.querySelector('.type-btn[data-type=vcard]');if(b)b.click()},200)" tabindex="0">
          <div class="ws-quick-card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          </div>
          <span class="ws-quick-card-label">联系方式</span>
        </button>
        <button class="ws-quick-card" onclick="app.switchTab('generator')" tabindex="0">
          <div class="ws-quick-card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>
          </div>
          <span class="ws-quick-card-label">更多</span>
        </button>
      </div>`,
        ranking: `
      <div class="ws-section-title">排行榜</div>
      <div class="ws-ranking-grid">
        <div class="ws-ranking-card">
          <h4>扫码排行 TOP5</h4>
          <div id="ws-rank-qrcode"></div>
        </div>
        <div class="ws-ranking-card">
          <h4>工单处理排行 TOP5</h4>
          <div id="ws-rank-workorder"></div>
        </div>
      </div>`,
        trend_chart: `
      <div class="ws-section-title">本周趋势</div>
      <div class="ws-trend-wrap">
        <div class="ws-trend-box">
          <h4>扫码趋势</h4>
          <div class="ws-chart"
            id="ws-chart-scan"></div>
        </div>
        <div class="ws-trend-box">
          <h4>工单趋势</h4>
          <div class="ws-chart"
            id="ws-chart-workorder"></div>
        </div>
      </div>`,
        quick_actions: `
      <div class="ws-section-title">快捷入口</div>
      <div class="ws-quick-grid">
        <button class="ws-quick-btn"
          onclick="app.goToSection('generator')">
          <span class="ws-quick-icon">+</span>
          <span>创建二维码</span></button>
        <button class="ws-quick-btn"
          onclick="app.goToSection('forms')">
          <span class="ws-quick-icon">+</span>
          <span>创建表单</span></button>
        <button class="ws-quick-btn"
          onclick="app.goToSection('workorders')">
          <span class="ws-quick-icon">+</span>
          <span>创建工单</span></button>
        <button class="ws-quick-btn"
          onclick="app.goToSection('qrcodes')">
          <span class="ws-quick-icon">+</span>
          <span>批量生成</span></button>
      </div>`
      };
      return maps[id] || `
    <div class="ws-section-title">
      ${titles[id] || id}</div>
    <div id="ws-content-${id}"></div>`;
    }

    renderHiddenBar() {
      const bar = document.getElementById('ws-hidden-bar');
      const list = document.getElementById('ws-hidden-list');
      if (!bar || !list) return;
      const hidden = this.currentLayout.filter(
        m => !m.visible);
      if (!hidden.length) {
        bar.classList.add('hidden'); return;
      }
      bar.classList.remove('hidden');
      list.innerHTML = hidden.map(m =>
        `<span class="ws-hidden-chip"
      onclick="app.showModule('${m.module_id}')">
      + ${this.wsModuleNames[m.module_id] || m.module_id}
    </span>`).join('');
    }

    showModule(id) {
      this.currentLayout = this.currentLayout.map(m =>
        m.module_id === id ? {...m, visible: true} : m);
      this.renderAllModules(this.currentLayout);
      this.saveLayout();
    }

    hideModule(id) {
      this.currentLayout = this.currentLayout.map(m =>
        m.module_id === id ? {...m, visible: false} : m);
      this.renderAllModules(this.currentLayout);
      this.saveLayout();
    }

    async saveLayout() {
      try {
        await fetch('/api/workspace/layout', {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            layout: this.currentLayout,
            theme: this.currentTheme || 'light'
          })
        });
      } catch(e) {
        console.error('保存布局失败', e);
      }
    }

    toggleEditMode() {
      this.isEditMode = !this.isEditMode;
      const modules = document.querySelectorAll('.ws-module');
      modules.forEach(m => {
        m.classList.toggle('edit-mode', this.isEditMode);
        m.draggable = this.isEditMode;
      });
      const btn = document.querySelector(
        '[onclick="app.toggleEditMode()"]');
      if (btn) btn.textContent =
        this.isEditMode ? '完成编辑' : '自定义布局';
      if (this.isEditMode) {
        this.bindDrag();
        this.injectHideBtns();
      } else {
        this.collectAndSaveOrder();
      }
    }

    injectHideBtns() {
      document.querySelectorAll('.ws-module').forEach(m => {
        if (m.querySelector('.ws-hide-btn')) return;
        const btn = document.createElement('div');
        btn.className = 'ws-hide-btn';
        btn.textContent = '隐藏';
        btn.style.cssText =
          'position:absolute;top:-10px;right:12px;' +
          'background:var(--danger);color:#fff;' +
          'font-size:11px;padding:1px 8px;' +
          'border-radius:4px;cursor:pointer;';
        btn.onclick = (e) => {
          e.stopPropagation();
          this.hideModule(m.dataset.moduleId);
        };
        m.style.position = 'relative';
        m.appendChild(btn);
      });
    }

    bindDrag() {
      const container = document.getElementById(
        'ws-modules-container');
      if (!container) return;
      container.querySelectorAll('.ws-module')
        .forEach(m => {
        m.addEventListener('dragstart', e => {
          m.classList.add('dragging');
          e.dataTransfer.effectAllowed = 'move';
        });
        m.addEventListener('dragend', () => {
          m.classList.remove('dragging');
        });
        m.addEventListener('dragover', e => {
          e.preventDefault();
          const dragging = container.querySelector(
            '.dragging');
          if (!dragging || dragging === m) return;
          const rect = m.getBoundingClientRect();
          if (e.clientY < rect.top + rect.height / 2) {
            container.insertBefore(dragging, m);
          } else {
            container.insertBefore(dragging, m.nextSibling);
          }
        });
      });
    }

    collectAndSaveOrder() {
      const modules = document.querySelectorAll(
        '#ws-modules-container .ws-module');
      this.currentLayout = [...modules].map((m, i) => ({
        module_id: m.dataset.moduleId,
        visible: !m.classList.contains('hidden'),
        order: i + 1
      }));
      this.saveLayout();
      document.querySelectorAll('.ws-hide-btn')
        .forEach(b => b.remove());
    }
}

// 初始化应用
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new SmartCodeApp();
    
    // 点击外部关闭下拉菜单（全局）
    document.addEventListener('click', function(e) {
        const dropdown = document.getElementById('top-nav-dropdown');
        const moreBtn = document.getElementById('nav-more-btn');
        if (dropdown && dropdown.classList.contains('show') && 
            !dropdown.contains(e.target) && !moreBtn.contains(e.target)) {
            dropdown.classList.remove('show');
        }
    });
});