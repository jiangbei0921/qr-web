/**
 * 智码云 - 二维码多终端预览中心
 * 设备外壳渲染器
 */
class DeviceRenderer {
    constructor(container) {
        this.container = container;
        this.shell = null;
        this.screen = null;
    }

    /**
     * 根据设备配置渲染设备外壳
     */
    render(deviceKey, config, orientation) {
        this.container.innerHTML = '';
        const cfg = JSON.parse(JSON.stringify(config));

        if (orientation === 'landscape') {
            [cfg.shell.width, cfg.shell.height] = [cfg.shell.height, cfg.shell.width];
            [cfg.shell.screenWidth, cfg.shell.screenHeight] = [cfg.shell.screenHeight, cfg.shell.screenWidth];
        }

        this.shell = document.createElement('div');
        this.shell.className = `preview-center__device-shell preview-center__device-shell--${cfg.shell.type}`;
        this.shell.style.width = cfg.shell.width + 'px';
        this.shell.style.height = cfg.shell.height + 'px';

        this.screen = document.createElement('div');
        this.screen.className = 'preview-center__device-screen';
        this.screen.style.marginLeft = cfg.shell.screenX + 'px';
        this.screen.style.marginTop = cfg.shell.screenY + 'px';
        this.screen.style.width = cfg.shell.screenWidth + 'px';
        this.screen.style.height = cfg.shell.screenHeight + 'px';
        this.screen.style.borderRadius = cfg.shell.borderRadius + 'px';

        this._renderShellDetails(cfg.shell);
        this.shell.appendChild(this.screen);
        this.container.appendChild(this.shell);
    }

    _renderShellDetails(shell) {
        if (shell.notch) {
            const notch = document.createElement('div');
            notch.className = 'preview-center__device-notch';
            notch.style.width = shell.notchWidth + 'px';
            notch.style.height = shell.notchHeight + 'px';
            this.screen.appendChild(notch);
        }

        if (shell.punchHole) {
            const hole = document.createElement('div');
            hole.className = 'preview-center__device-punch-hole';
            hole.style.width = (shell.punchHoleSize || 12) + 'px';
            hole.style.height = (shell.punchHoleSize || 12) + 'px';
            this.screen.appendChild(hole);
        }

        if (shell.homeIndicator) {
            const indicator = document.createElement('div');
            indicator.className = 'preview-center__device-home-indicator';
            this.screen.appendChild(indicator);
        }

        if (shell.browserFrame) {
            const topbar = document.createElement('div');
            topbar.className = 'preview-center__browser-topbar';
            topbar.style.height = shell.browserBar + 'px';
            topbar.innerHTML = `
                <span class="preview-center__browser-dot preview-center__browser-dot--red"></span>
                <span class="preview-center__browser-dot preview-center__browser-dot--yellow"></span>
                <span class="preview-center__browser-dot preview-center__browser-dot--green"></span>
                <span class="preview-center__browser-url">🔒 smartcode.cn</span>`;
            this.screen.appendChild(topbar);
        }

        if (shell.wechatTopBar) {
            const topbar = document.createElement('div');
            topbar.className = 'preview-center__wechat-topbar';
            topbar.style.height = shell.topBarHeight + 'px';
            topbar.style.lineHeight = shell.topBarHeight + 'px';
            topbar.textContent = '微信';
            this.screen.appendChild(topbar);
        }

        if (shell.wechatBottomBar) {
            const bottombar = document.createElement('div');
            bottombar.className = 'preview-center__wechat-bottombar';
            bottombar.style.height = shell.bottomBarHeight + 'px';
            bottombar.innerHTML = `
                <span class="preview-center__wechat-tab preview-center__wechat-tab--active">微信</span>
                <span class="preview-center__wechat-tab">通讯录</span>
                <span class="preview-center__wechat-tab">发现</span>
                <span class="preview-center__wechat-tab">我</span>`;
            this.screen.appendChild(bottombar);
        }
    }

    getScreenElement() {
        return this.screen;
    }

    getShellElement() {
        return this.shell;
    }
}