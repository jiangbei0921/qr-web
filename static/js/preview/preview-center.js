/**
 * 智码云 - 二维码多终端预览中心
 * 主控制器
 * 
 * 使用方式：
 *   const pc = new PreviewCenter({
 *       container: '#previewCenter',
 *       qrcodeId: 123
 *   });
 *   pc.open();
 */
class PreviewCenter {
    constructor(options) {
        this.options = Object.assign({
            container: '#previewCenter',
            qrcodeId: null,
            onClose: null
        }, options);

        this.container = null;
        this.deviceRenderer = null;
        this.qrRenderer = null;
        this.captureService = null;
        this.pdfService = null;

        this.currentDevice = 'iphone';
        this.currentTheme = 'auto';
        this.currentOrientation = 'portrait';
        this.currentZoom = 0.8;
        this.qrData = null;
        this.isOpen = false;
        this._rafId = null;
    }

    /**
     * 初始化并打开预览中心
     */
    async open() {
        if (this.isOpen) return;
        this.isOpen = true;

        this.container = document.querySelector(this.options.container);
        if (!this.container) {
            this._createContainer();
        }

        this._bindEvents();
        this._applyTheme(this.currentTheme);
        this._applyZoom(this.currentZoom);

        this.deviceRenderer = new DeviceRenderer(this.container.querySelector('#previewViewport'));
        this.qrRenderer = new QRRenderer();
        this.captureService = new CaptureService();
        this.pdfService = new PDFService();

        await this._loadPreferences();
        await this._loadQRData();
        this._renderAll();
    }

    /**
     * 关闭预览中心
     */
    close() {
        if (!this.isOpen) return;
        this.isOpen = false;

        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }

        if (this.qrRenderer) {
            this.qrRenderer.destroy();
            this.qrRenderer = null;
        }

        if (this.container && this.container.parentElement) {
            this.container.parentElement.removeChild(this.container);
        }
        this.container = null;

        if (typeof this.options.onClose === 'function') {
            this.options.onClose();
        }
    }

    /**
     * 切换设备
     */
    switchDevice(deviceKey) {
        if (!DEVICE_CONFIG[deviceKey] || this.currentDevice === deviceKey) return;
        this.currentDevice = deviceKey;
        const cfg = DEVICE_CONFIG[deviceKey];
        this.currentOrientation = cfg.defaultOrientation;
        this.currentZoom = cfg.zoom.default;
        this._applyZoom(this.currentZoom);
        this._renderAll();
        this._savePreferences();
        this._updateDeviceListUI();
    }

    /**
     * 切换主题
     */
    switchTheme(theme) {
        if (this.currentTheme === theme) return;
        this.currentTheme = theme;
        this._applyTheme(theme);
        this._savePreferences();
    }

    /**
     * 切换方向
     */
    switchOrientation() {
        this.currentOrientation = this.currentOrientation === 'portrait' ? 'landscape' : 'portrait';
        this._renderAll();
        this._savePreferences();
    }

    /**
     * 缩放
     */
    zoomIn() {
        const idx = ZOOM_LEVELS.indexOf(this.currentZoom);
        if (idx < ZOOM_LEVELS.length - 1) {
            this.currentZoom = ZOOM_LEVELS[idx + 1];
            this._applyZoom(this.currentZoom);
            this._savePreferences();
        }
    }

    zoomOut() {
        const idx = ZOOM_LEVELS.indexOf(this.currentZoom);
        if (idx > 0) {
            this.currentZoom = ZOOM_LEVELS[idx - 1];
            this._applyZoom(this.currentZoom);
            this._savePreferences();
        }
    }

    zoomReset() {
        const cfg = DEVICE_CONFIG[this.currentDevice];
        this.currentZoom = cfg.zoom.default;
        this._applyZoom(this.currentZoom);
        this._savePreferences();
    }

    /**
     * 截图
     */
    async takeScreenshot() {
        if (!this.captureService) return;
        const shell = this.deviceRenderer.getShellElement();
        if (!shell) return;

        CaptureService.flash(shell);

        const title = (this.qrData && this.qrData.title) || 'qrcode';
        const filename = `${title}-${this.currentDevice}-${Date.now()}.png`;

        try {
            await this.captureService.captureAndDownload(shell, filename, {
                format: 'png',
                scale: 2
            });
        } catch (e) {
            console.error('截图失败:', e);
            alert('截图失败，请刷新页面后重试');
        }
    }

    /**
     * 导出 PDF
     */
    async exportPDF() {
        if (!this.pdfService) return;
        const shell = this.deviceRenderer.getShellElement();
        if (!shell) return;

        const title = (this.qrData && this.qrData.title) || '二维码预览';

        try {
            await this.pdfService.exportPDF(shell, {
                pageSize: 'a4',
                orientation: 'portrait',
                title: title,
                includeMeta: true
            });
        } catch (e) {
            console.error('PDF 导出失败:', e);
            alert('PDF 导出失败，请刷新页面后重试');
        }
    }

    /**
     * 实时刷新（由外部调用）
     */
    refresh(qrData) {
        if (!this.isOpen) return;
        this.qrData = qrData;
        if (this._rafId) cancelAnimationFrame(this._rafId);
        this._rafId = requestAnimationFrame(() => {
            this._renderQR();
            this._rafId = null;
        });
    }

    // ========== 内部方法 ==========

    _createContainer() {
        const container = document.createElement('div');
        container.id = 'previewCenter';
        container.className = 'preview-center';
        container.innerHTML = this._getTemplate();
        document.body.appendChild(container);
        this.container = container;
    }

    _getTemplate() {
        return `
            <aside class="preview-center__sidebar">
                <div class="preview-center__sidebar-header"><h3>选择设备</h3></div>
                <ul class="preview-center__device-list" id="deviceList"></ul>
                <div class="preview-center__sidebar-footer">
                    <p class="preview-center__hint">点击设备切换预览</p>
                </div>
            </aside>
            <main class="preview-center__viewport" id="previewViewport"></main>
            <footer class="preview-center__toolbar" id="toolbar">
                <div class="preview-center__toolbar-group">
                    <button class="preview-center__btn" data-action="theme" title="切换主题">
                        <span class="preview-center__btn-icon">🌙</span>
                        <span class="preview-center__btn-label">主题</span>
                    </button>
                    <button class="preview-center__btn" data-action="orientation" title="旋转屏幕">
                        <span class="preview-center__btn-icon">🔄</span>
                        <span class="preview-center__btn-label">旋转</span>
                    </button>
                </div>
                <div class="preview-center__toolbar-group">
                    <div class="preview-center__zoom-control">
                        <button class="preview-center__btn preview-center__btn--sm" data-action="zoom-out">−</button>
                        <span class="preview-center__zoom-label" id="zoomLabel">80%</span>
                        <button class="preview-center__btn preview-center__btn--sm" data-action="zoom-in">+</button>
                        <button class="preview-center__btn preview-center__btn--sm" data-action="zoom-reset">重置</button>
                    </div>
                </div>
                <div class="preview-center__toolbar-group">
                    <button class="preview-center__btn preview-center__btn--primary" data-action="screenshot">
                        <span class="preview-center__btn-icon">📷</span>
                        <span class="preview-center__btn-label">截图</span>
                    </button>
                    <button class="preview-center__btn preview-center__btn--primary" data-action="pdf">
                        <span class="preview-center__btn-icon">📄</span>
                        <span class="preview-center__btn-label">导出PDF</span>
                    </button>
                </div>
            </footer>`;
    }

    _bindEvents() {
        this._renderDeviceList();

        const toolbar = this.container.querySelector('#toolbar');
        toolbar.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;
            const action = btn.dataset.action;
            switch (action) {
                case 'theme': this._cycleTheme(); break;
                case 'orientation': this.switchOrientation(); break;
                case 'zoom-in': this.zoomIn(); break;
                case 'zoom-out': this.zoomOut(); break;
                case 'zoom-reset': this.zoomReset(); break;
                case 'screenshot': this.takeScreenshot(); break;
                case 'pdf': this.exportPDF(); break;
            }
        });

        const deviceList = this.container.querySelector('#deviceList');
        deviceList.addEventListener('click', (e) => {
            const item = e.target.closest('[data-device]');
            if (!item) return;
            this.switchDevice(item.dataset.device);
        });
    }

    _renderDeviceList() {
        const list = this.container.querySelector('#deviceList');
        list.innerHTML = '';
        Object.entries(DEVICE_CONFIG).forEach(([key, cfg]) => {
            const li = document.createElement('li');
            li.className = 'preview-center__device-item';
            if (key === this.currentDevice) li.classList.add('preview-center__device-item--active');
            li.dataset.device = key;
            li.innerHTML = `
                <span class="preview-center__device-item-icon">${cfg.icon}</span>
                <span class="preview-center__device-item-name">${cfg.name}</span>
                <span class="preview-center__device-item-category">${cfg.category}</span>`;
            list.appendChild(li);
        });
    }

    _updateDeviceListUI() {
        const items = this.container.querySelectorAll('.preview-center__device-item');
        items.forEach(item => {
            item.classList.toggle('preview-center__device-item--active', item.dataset.device === this.currentDevice);
        });
    }

    _cycleTheme() {
        const themes = ['light', 'dark', 'auto'];
        const idx = themes.indexOf(this.currentTheme);
        this.switchTheme(themes[(idx + 1) % themes.length]);
    }

    _applyTheme(theme) {
        if (this.container) {
            this.container.setAttribute('data-theme', theme);
        }
    }

    _applyZoom(zoom) {
        if (!this.container) return;
        const shell = this.container.querySelector('.preview-center__device-shell');
        if (shell) {
            shell.setAttribute('data-zoom', zoom.toFixed(1));
        }
        const orientation = this.container.getAttribute('data-orientation') || 'portrait';
        this.container.setAttribute('data-orientation', orientation);

        const zoomLabel = this.container.querySelector('#zoomLabel');
        if (zoomLabel) {
            zoomLabel.textContent = Math.round(zoom * 100) + '%';
        }
    }

    _renderAll() {
        if (!this.container || !this.deviceRenderer) return;
        const cfg = DEVICE_CONFIG[this.currentDevice];
        if (!cfg) return;

        this.deviceRenderer.render(this.currentDevice, cfg, this.currentOrientation);
        this._applyZoom(this.currentZoom);

        if (this.qrRenderer) {
            this.qrRenderer.destroy();
            this.qrRenderer = new QRRenderer();
        }
        const screen = this.deviceRenderer.getScreenElement();
        if (screen) {
            this.qrRenderer.init(screen);
            this._renderQR();
        }
    }

    _renderQR() {
        if (this.qrRenderer && this.qrData) {
            this.qrRenderer.render(this.qrData);
        }
    }

    async _loadQRData() {
        if (!this.options.qrcodeId) return;
        try {
            const resp = await fetch(`/api/qrcodes/${this.options.qrcodeId}/preview-data`);
            const result = await resp.json();
            if (result.success) {
                this.qrData = result.data;
            }
        } catch (e) {
            console.error('加载二维码数据失败:', e);
        }
    }

    async _loadPreferences() {
        if (!this.options.qrcodeId) return;
        try {
            const resp = await fetch(`/api/qrcodes/${this.options.qrcodeId}/preview-preferences`);
            const result = await resp.json();
            if (result.success && result.data) {
                const p = result.data;
                this.currentDevice = p.last_device || 'iphone';
                this.currentTheme = p.theme || 'auto';
                this.currentOrientation = p.orientation || 'portrait';
                this.currentZoom = p.zoom_level || 0.8;
            }
        } catch (e) {
            /* 使用默认值 */
        }
        this._applyTheme(this.currentTheme);
    }

    async _savePreferences() {
        if (!this.options.qrcodeId) return;
        try {
            await fetch(`/api/qrcodes/${this.options.qrcodeId}/preview-preferences`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    last_device: this.currentDevice,
                    theme: this.currentTheme,
                    orientation: this.currentOrientation,
                    zoom_level: this.currentZoom
                })
            });
        } catch (e) {
            /* 静默失败 */
        }
    }
}