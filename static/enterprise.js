/**
 * 智码云企业级平台 - 前端交互逻辑
 */

class SmartCodeEnterprise {
    constructor() {
        this.userId = null;
        this.orgId = null;
        this.username = null;
        this.currentSection = 'dashboard';
        this.qrcodes = [];
        
        this.init();
    }

    init() {
        this.checkAuth();
        this.setupEventListeners();
        this.initVersionManager();
        this.initNotificationCenter();
        this.initSearchCenter();
        this.initBatchCenter();
    }

    // ============ 认证 ============

    async checkAuth() {
        try {
            const response = await fetch('/api/auth/check');
            const data = await response.json();
            
            if (data.authenticated) {
                this.userId = data.user_id;
                this.orgId = data.org_id;
                this.username = data.username;
                this.showApp();
            } else {
                this.showAuth();
            }
        } catch (error) {
            console.error('认证检查失败:', error);
            this.showAuth();
        }
    }

    async login(email, password) {
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });

            const data = await response.json();

            if (data.success) {
                this.userId = data.user_id;
                this.orgId = data.org_id;
                this.username = data.user_id;
                this.showApp();
                this.notify('登录成功');
                return true;
            } else {
                this.notify(data.error, 'error');
                return false;
            }
        } catch (error) {
            this.notify('登录失败', 'error');
            return false;
        }
    }

    async register(username, email, password, orgName) {
        try {
            const response = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username,
                    email,
                    password,
                    org_name: orgName
                })
            });

            const data = await response.json();

            if (data.success) {
                this.userId = data.user_id;
                this.orgId = data.org_id;
                this.showApp();
                this.notify('注册成功');
                return true;
            } else {
                this.notify(data.error, 'error');
                return false;
            }
        } catch (error) {
            this.notify('注册失败', 'error');
            return false;
        }
    }

    async logout() {
        try {
            await fetch('/api/auth/logout', { method: 'POST' });
            this.userId = null;
            this.orgId = null;
            this.username = null;
            this.showAuth();
            this.notify('已登出');
        } catch (error) {
            this.notify('登出失败', 'error');
        }
    }

    showAuth() {
        document.getElementById('auth-section').style.display = 'flex';
        document.getElementById('app-section').style.display = 'none';
    }

    showApp() {
        document.getElementById('auth-section').style.display = 'none';
        document.getElementById('app-section').style.display = 'flex';
        document.getElementById('username-display').textContent = this.username;
        this.loadDashboard();
    }

    // ============ 事件监听 ============

    setupEventListeners() {
        // 登录表单
        document.getElementById('login-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('login-email')?.value;
            const password = document.getElementById('login-password')?.value;
            if (email && password && await this.login(email, password)) {
                document.getElementById('login-form').reset();
            }
        });

        // 注册表单
        document.getElementById('register-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('register-username')?.value;
            const email = document.getElementById('register-email')?.value;
            const password = document.getElementById('register-password')?.value;
            const orgName = document.getElementById('register-org')?.value || username;
            if (username && email && password && await this.register(username, email, password, orgName)) {
                document.getElementById('register-form').reset();
            }
        });

        // 登出按钮
        document.getElementById('logout-btn')?.addEventListener('click', () => this.logout());

        // 导航菜单
        document.querySelectorAll('[data-section]').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const section = item.dataset.section;
                this.switchSection(section);
            });
        });

        // 创建活码按钮
        document.getElementById('create-qrcode-btn')?.addEventListener('click', () => {
            openModal('create-qrcode-modal');
        });

        // 创建活码表单
        document.getElementById('create-qrcode-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            await this.createQrcode();
        });
    }

    // ============ 仪表板 ============

    async loadDashboard() {
        try {
            await this.loadRecentContent();
            await this.loadContinueCreating();
            await this.loadRecommendedTemplates();
        } catch (error) {
            console.error('加载仪表板失败:', error);
        }
    }

    toggleStats() {
        const body = document.getElementById('ds-body');
        const icon = document.getElementById('ds-toggle-icon');
        if (!body || !icon) return;

        const isOpen = body.style.display !== 'none';
        if (isOpen) {
            body.style.display = 'none';
            icon.classList.remove('ds-open');
        } else {
            body.style.display = 'block';
            icon.classList.add('ds-open');
            if (!this.statsLoaded) {
                this.loadStats();
            }
        }
    }

    async loadStats() {
        this.statsLoaded = true;
        try {
            const response = await fetch('/api/dashboard/stats');
            const data = await response.json();

            if (data.success) {
                const stats = data.stats;
                const mappings = [
                    { id: 'stat-qrcodes', value: stats.qrcode_count },
                    { id: 'stat-scans', value: stats.total_scans },
                    { id: 'stat-submissions', value: stats.submission_count },
                    { id: 'stat-today', value: stats.today_scans },
                    { id: 'stat-week', value: stats.week_scans },
                    { id: 'stat-links', value: stats.total_dynamic_links }
                ];

                mappings.forEach(({ id, value }) => {
                    const el = document.getElementById(id);
                    if (el) {
                        el.setAttribute('data-target', value);
                        this.countUp(el, value);
                    }
                });
            }
        } catch (error) {
            console.error('加载统计失败:', error);
        }
    }

    countUp(el, target, duration = 1200) {
        const start = parseInt(el.textContent) || 0;
        const startTime = performance.now();
        const step = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            const current = Math.floor(start + (target - start) * eased);
            el.textContent = current.toLocaleString();
            if (progress < 1) {
                requestAnimationFrame(step);
            }
        };
        requestAnimationFrame(step);
    }

    navigateToScene(scene) {
        const sceneMap = {
            'personal': '个人主页',
            'work': '求职工作',
            'study': '学习教育',
            'activity': '活动组织',
            'business': '商业经营',
            'family': '个人主页'
        };
        const category = sceneMap[scene] || '';
        window.location.href = '/templates-center' + (category ? '?category=' + encodeURIComponent(category) : '');
    }

    async loadRecommendedTemplates() {
        const track = document.getElementById('rt-carousel-track');
        if (!track) return;

        track.innerHTML = `
            <div class="rt-skeleton">
                <div class="rt-skeleton-card"></div>
                <div class="rt-skeleton-card"></div>
                <div class="rt-skeleton-card"></div>
            </div>`;

        try {
            const response = await fetch('/api/templates');
            const data = await response.json();

            if (data.success && data.templates) {
                const templates = data.templates.slice(0, 12);
                track.innerHTML = templates.map((t, i) => `
                    <div class="rt-slide" data-index="${i}">
                        <div class="rt-card">
                            <div class="rt-card-cover">
                                <div class="rt-card-cover-inner">
                                    <span class="rt-card-type-icon">${this.getTemplateIcon(t.type)}</span>
                                </div>
                            </div>
                            <div class="rt-card-body">
                                <h4 class="rt-card-title">${this.escapeHtml(t.name)}</h4>
                                <p class="rt-card-desc">${this.escapeHtml(t.description || '')}</p>
                                <div class="rt-card-meta">
                                    <span class="rt-meta-uses">${(t.use_count || 0).toLocaleString()} 使用</span>
                                    <button class="rt-meta-fav" onclick="event.stopPropagation()">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
                                    </button>
                                </div>
                                <button class="rt-card-btn" onclick="event.stopPropagation(); window.enterpriseApp.useTemplate('${t.name}')">立即创建</button>
                            </div>
                        </div>
                    </div>`).join('');

                this.initCarousel(track);
            }
        } catch (error) {
            console.error('加载推荐模板失败:', error);
            track.innerHTML = '';
        }
    }

    getTemplateIcon(type) {
        const icons = {
            'text': '📝', 'url': '🔗', 'vcard': '👤', 'wifi': '📶',
            'email': '✉️', 'questionnaire': '📋', 'form': '📄', 'media': '🎬',
            'image': '🖼️', 'file': '📁'
        };
        return icons[type] || '📝';
    }

    initCarousel(track) {
        const slides = track.querySelectorAll('.rt-slide');
        const leftArrow = document.getElementById('rt-arrow-left');
        const rightArrow = document.getElementById('rt-arrow-right');
        const dotsContainer = document.getElementById('rt-dots');
        let currentIndex = 0;

        if (slides.length === 0) return;

        const renderDots = () => {
            if (!dotsContainer) return;
            dotsContainer.innerHTML = '';
            for (let i = 0; i < slides.length; i++) {
                const dot = document.createElement('span');
                dot.className = 'rt-dot' + (i === currentIndex ? ' active' : '');
                dot.onclick = () => goTo(i);
                dotsContainer.appendChild(dot);
            }
        };

        const updateSlides = () => {
            slides.forEach((slide, i) => {
                slide.classList.remove('rt-active', 'rt-prev', 'rt-next');
                if (i === currentIndex) {
                    slide.classList.add('rt-active');
                } else if (i === currentIndex - 1 || (currentIndex === 0 && i === slides.length - 1)) {
                    slide.classList.add('rt-prev');
                } else if (i === currentIndex + 1 || (currentIndex === slides.length - 1 && i === 0)) {
                    slide.classList.add('rt-next');
                }
            });
            renderDots();
            this.updateArrowVisibility(currentIndex, slides.length, leftArrow, rightArrow);
        };

        const goTo = (index) => {
            currentIndex = ((index % slides.length) + slides.length) % slides.length;
            const offset = currentIndex * -100 / 3;
            track.style.transform = `translateX(${offset}%)`;
            updateSlides();
        };

        leftArrow.onclick = () => goTo(currentIndex - 1);
        rightArrow.onclick = () => goTo(currentIndex + 1);

        let touchStartX = 0;
        track.addEventListener('touchstart', (e) => { touchStartX = e.touches[0].clientX; }, { passive: true });
        track.addEventListener('touchend', (e) => {
            const diff = touchStartX - e.changedTouches[0].clientX;
            if (Math.abs(diff) > 40) {
                goTo(currentIndex + (diff > 0 ? 1 : -1));
            }
        });

        goTo(0);
    }

    updateArrowVisibility(index, total, leftArrow, rightArrow) {
        if (leftArrow) leftArrow.style.display = total <= 1 ? 'none' : '';
        if (rightArrow) rightArrow.style.display = total <= 1 ? 'none' : '';
    }

    useTemplate(templateName) {
        window.location.href = '/?tab=generator&template=' + encodeURIComponent(templateName);
    }

    async loadRecentContent(page = 1) {
        const grid = document.getElementById('rc-grid');
        const pagination = document.getElementById('rc-pagination');
        if (!grid) return;

        this.recentContentPage = page;

        try {
            const response = await fetch(`/api/qrcodes/list?page=${page}&size=9`);
            const data = await response.json();

            if (data.success) {
                this.qrcodes = data.qrcodes;
                const total = data.total || 0;
                const totalPages = Math.ceil(total / 9);

                if (!data.qrcodes || data.qrcodes.length === 0) {
                    grid.innerHTML = `
                        <div class="rc-card rc-card-empty" style="grid-column: 1/-1;">
                            <div class="rc-empty-icon">📝</div>
                            <p class="rc-empty-text">还没有内容</p>
                            <p class="rc-empty-hint">点击"创建内容"开始你的第一个二维码</p>
                        </div>`;
                } else {
                    grid.innerHTML = data.qrcodes.map(qr => {
                        const title = qr.title || '未命名';
                        const type = qr.category || 'text';
                        const typeLabel = this.getTypeLabel(type);
                        const updatedAt = this.formatRelativeTime(qr.updated_at || qr.created_at);
                        const scanCount = qr.scan_count || 0;
                        const viewCount = qr.view_count || 0;

                        return `
                            <div class="rc-card" onclick="window.enterpriseApp.viewRecentContent(${qr.id})">
                                <h4 class="rc-card-title">${this.escapeHtml(title)}</h4>
                                <div class="rc-card-meta">
                                    <span class="rc-card-type">${typeLabel}</span>
                                    <span class="rc-card-time">${updatedAt}</span>
                                </div>
                                <div class="rc-card-stats">
                                    <span class="rc-stat">👁 ${viewCount} 浏览</span>
                                    <span class="rc-stat">📱 ${scanCount} 扫码</span>
                                </div>
                            </div>`;
                    }).join('');
                }

                this.renderRecentContentPagination(total, totalPages, page);
            }
        } catch (error) {
            console.error('加载最近内容失败:', error);
            grid.innerHTML = `
                <div class="rc-card rc-card-empty" style="grid-column: 1/-1;">
                    <div class="rc-empty-icon">⚠️</div>
                    <p class="rc-empty-text">加载失败</p>
                    <p class="rc-empty-hint">请刷新页面重试</p>
                </div>`;
        }
    }

    renderRecentContentPagination(total, totalPages, currentPage) {
        const pagination = document.getElementById('rc-pagination');
        if (!pagination) return;

        if (totalPages <= 1) {
            pagination.style.display = 'none';
            return;
        }

        pagination.style.display = 'flex';
        let html = `<button class="rc-page-btn" ${currentPage <= 1 ? 'disabled' : ''} onclick="window.enterpriseApp.loadRecentContent(${currentPage - 1})">上一页</button>`;

        const start = Math.max(1, currentPage - 2);
        const end = Math.min(totalPages, currentPage + 2);
        for (let i = start; i <= end; i++) {
            html += `<button class="rc-page-btn${i === currentPage ? ' active' : ''}" onclick="window.enterpriseApp.loadRecentContent(${i})">${i}</button>`;
        }

        html += `<button class="rc-page-btn" ${currentPage >= totalPages ? 'disabled' : ''} onclick="window.enterpriseApp.loadRecentContent(${currentPage + 1})">下一页</button>`;
        html += `<span class="rc-page-info">共 ${total} 条</span>`;
        pagination.innerHTML = html;
    }

    getTypeLabel(type) {
        const labels = {
            'text': '文本', 'url': '网址', 'file': '文件', 'image': '图片',
            'media': '音视频', 'vcard': '名片', 'wifi': 'WiFi', 'email': '邮件',
            'questionnaire': '问卷', 'form': '表格'
        };
        return labels[type] || type || '文本';
    }

    viewRecentContent(qrcodeId) {
        window.location.href = `/?tab=generator&edit=${qrcodeId}`;
    }

    // ============ 活码管理 ============

    async createQrcode() {
        const title = document.getElementById('qrcode-title')?.value;
        const type = document.getElementById('qrcode-type')?.value || 'text';
        const style = document.querySelector('input[name="qr-style"]:checked')?.value || 'square';
        const color = document.getElementById('qrcode-color')?.value || '#000000';

        if (!title) {
            this.notify('请输入活码标题', 'error');
            return;
        }

        try {
            const response = await fetch('/api/qrcodes/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title,
                    content: { type },
                    config: {
                        style,
                        fill_color: color,
                        back_color: '#FFFFFF'
                    }
                })
            });

            const data = await response.json();

            if (data.success) {
                this.notify('活码创建成功');
                closeModal('create-qrcode-modal');
                document.getElementById('create-qrcode-form').reset();
                
                // 刷新列表
                this.loadDashboard();
            } else {
                this.notify(data.error || '创建失败', 'error');
            }
        } catch (error) {
            console.error('创建活码失败:', error);
            this.notify('创建活码失败: ' + error.message, 'error');
        }
    }

    downloadQrcode(base64, name) {
        const link = document.createElement('a');
        link.href = base64;
        link.download = `${name}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        this.notify('已下载');
    }

    viewQrcode(qrcodeId) {
        this.notify('功能开发中...');
    }

    // ============ 页面切换 ============

    switchSection(section) {
        // 更新导航
        document.querySelectorAll('[data-section]').forEach(item => {
            item.classList.remove('active');
            if (item.dataset.section === section) {
                item.classList.add('active');
            }
        });

        // 更新内容
        document.querySelectorAll('[id$="-section"]').forEach(sec => {
            sec.classList.remove('active');
        });
        const targetSection = document.getElementById(`${section}-section`);
        if (targetSection) {
            targetSection.classList.add('active');
        }

        // 加载相关数据
        if (section === 'dashboard') {
            this.loadDashboard();
        } else if (section === 'qrcodes') {
            this.loadQrcodes();
        }

        this.currentSection = section;
    }

    async loadQrcodes() {
        try {
            const response = await fetch('/api/qrcodes/list');
            const data = await response.json();
            const grid = document.getElementById('qrcodes-grid');

            if (!grid) return; // 确保元素存在

            if (data.success) {
                grid.innerHTML = '';

                if (!data.qrcodes || data.qrcodes.length === 0) {
                    grid.innerHTML = '<div class="qrcode-card placeholder" style="grid-column: 1/-1; text-align: center; padding: 40px;"><p>点击右上角"新建活码"开始</p></div>';
                } else {
                    data.qrcodes.forEach(qr => {
                        const card = document.createElement('div');
                        card.className = 'qrcode-card';
                        card.innerHTML = `
                            <h4>${qr.title}</h4>
                            <p style="font-size: 12px; color: #666; margin: 8px 0;">扫码: ${qr.scan_count || 0} 次</p>
                            <span class="status-badge">${qr.status || 'normal'}</span>
                        `;
                        grid.appendChild(card);
                    });
                }
            }
        } catch (error) {
            console.error('加载活码失败:', error);
        }
    }

    // ============ 版本管理 ============

    initVersionManager() {
        this.versionCurrentResourceType = 'qrcode';
        this.versionCurrentResourceId = null;
        this.versionList = [];
        this.versionSelectedId = null;
        this.versionPendingRollbackId = null;

        document.getElementById('version-search-btn')?.addEventListener('click', () => this.searchVersions());
        document.getElementById('version-resource-type')?.addEventListener('change', (e) => {
            this.versionCurrentResourceType = e.target.value;
        });
        document.getElementById('version-resource-id')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.searchVersions();
        });
        document.getElementById('version-refresh-btn')?.addEventListener('click', () => this.searchVersions());
        document.getElementById('version-compare-btn')?.addEventListener('click', () => this.openCompareModal());
        document.getElementById('version-rollback-btn')?.addEventListener('click', () => this.openRollbackModal());
        document.getElementById('version-compare-execute')?.addEventListener('click', () => this.executeCompare());
        document.getElementById('version-rollback-confirm')?.addEventListener('click', () => this.executeRollback());
        document.getElementById('version-remark-save')?.addEventListener('click', () => this.saveVersionRemark());
    }

    async searchVersions() {
        const resourceType = document.getElementById('version-resource-type')?.value || 'qrcode';
        const resourceId = document.getElementById('version-resource-id')?.value?.trim();
        this.versionCurrentResourceType = resourceType;

        if (!resourceId) {
            this.notify('请输入资源ID', 'error');
            return;
        }

        this.versionCurrentResourceId = resourceId;

        try {
            const response = await fetch(`/api/versions?type=${resourceType}&id=${resourceId}`);
            const data = await response.json();

            if (data.success) {
                this.versionList = data.versions;
                this.renderVersionTimeline(data.versions, data.total);
                this.versionSelectedId = null;
                this.updateDetailPanel(null);
            } else {
                this.notify(data.error || '查询失败', 'error');
            }
        } catch (error) {
            console.error('版本查询失败:', error);
            this.notify('查询版本失败', 'error');
        }
    }

    renderVersionTimeline(versions, total) {
        const timeline = document.getElementById('version-timeline');
        const countLabel = document.getElementById('version-count-label');

        if (!timeline) return;

        countLabel.textContent = `共 ${total} 个版本`;

        if (!versions || versions.length === 0) {
            timeline.innerHTML = `
                <div class="version-empty">
                    <div class="version-empty-icon">📋</div>
                    <p>暂无版本历史记录</p>
                </div>`;
            return;
        }

        const latestVersion = versions[0]?.version;

        timeline.innerHTML = versions.map((v, index) => {
            const isLatest = v.version === latestVersion;
            const timeStr = v.created_at ? new Date(v.created_at).toLocaleString('zh-CN') : '-';
            const remark = v.remark || '';
            const isActive = v.id === this.versionSelectedId;

            return `
            <div class="version-timeline-item ${isLatest ? 'version-latest' : ''} ${isActive ? 'version-active' : ''}"
                 data-version-id="${v.id}"
                 onclick="window.enterpriseApp.selectVersion(${v.id})">
                <div class="version-timeline-dot ${isLatest ? 'dot-latest' : ''}"></div>
                <div class="version-timeline-content">
                    <div class="version-timeline-top">
                        <span class="version-number">v${v.version}</span>
                        ${isLatest ? '<span class="version-badge-latest">最新</span>' : ''}
                        <span class="version-operator">${this.escapeHtml(v.operator)}</span>
                    </div>
                    ${remark ? `<div class="version-remark-text">${this.escapeHtml(remark)}</div>` : ''}
                    <div class="version-time">${timeStr}</div>
                    <div class="version-actions">
                        <button class="btn-tiny" onclick="event.stopPropagation(); window.enterpriseApp.editVersionRemark(${v.id}, '${this.escapeAttr(remark)}')">备注</button>
                        <button class="btn-tiny btn-tiny-danger" onclick="event.stopPropagation(); window.enterpriseApp.deleteVersion(${v.id})">删除</button>
                    </div>
                </div>
            </div>`;
        }).join('');
    }

    async selectVersion(versionId) {
        this.versionSelectedId = versionId;

        document.querySelectorAll('.version-timeline-item').forEach(el => {
            el.classList.toggle('version-active', el.dataset.versionId == versionId);
        });

        try {
            const response = await fetch(`/api/versions/${versionId}`);
            const data = await response.json();

            if (data.success) {
                this.updateDetailPanel(data.version);
                document.getElementById('version-compare-btn').disabled = false;
                document.getElementById('version-rollback-btn').disabled = false;
            }
        } catch (error) {
            console.error('版本详情查询失败:', error);
            this.notify('查询版本详情失败', 'error');
        }
    }

    updateDetailPanel(version) {
        const panel = document.getElementById('version-detail-content');
        if (!panel) return;

        if (!version) {
            panel.innerHTML = `
                <div class="version-empty">
                    <div class="version-empty-icon">📄</div>
                    <p>点击左侧版本查看详情</p>
                </div>`;
            document.getElementById('version-compare-btn').disabled = true;
            document.getElementById('version-rollback-btn').disabled = true;
            return;
        }

        const timeStr = version.created_at ? new Date(version.created_at).toLocaleString('zh-CN') : '-';
        const snapshot = version.snapshot || {};
        const snapshotKeys = Object.keys(snapshot);

        panel.innerHTML = `
            <div class="version-detail-meta">
                <div class="version-detail-row">
                    <span class="version-detail-label">版本号</span>
                    <span class="version-detail-value version-number-large">v${version.version}</span>
                </div>
                <div class="version-detail-row">
                    <span class="version-detail-label">操作者</span>
                    <span class="version-detail-value">${this.escapeHtml(version.operator)}</span>
                </div>
                <div class="version-detail-row">
                    <span class="version-detail-label">时间</span>
                    <span class="version-detail-value">${timeStr}</span>
                </div>
                <div class="version-detail-row">
                    <span class="version-detail-label">备注</span>
                    <span class="version-detail-value">${this.escapeHtml(version.remark || '无')}</span>
                </div>
                <div class="version-detail-row">
                    <span class="version-detail-label">哈希</span>
                    <span class="version-detail-value version-hash">${version.content_hash ? version.content_hash.substring(0, 12) + '...' : '-'}</span>
                </div>
            </div>
            <div class="version-detail-snapshot">
                <h4>版本快照 (${snapshotKeys.length} 个字段)</h4>
                <div class="version-snapshot-fields">
                    ${snapshotKeys.map(key => `
                        <div class="snapshot-field">
                            <span class="snapshot-field-key">${this.escapeHtml(key)}</span>
                            <span class="snapshot-field-value">${this.escapeHtml(String(snapshot[key]).substring(0, 200))}</span>
                        </div>
                    `).join('')}
                </div>
            </div>`;
    }

    openCompareModal() {
        if (!this.versionList || this.versionList.length < 2) {
            this.notify('至少需要2个版本才能比较', 'error');
            return;
        }

        const v1Select = document.getElementById('compare-v1-select');
        const v2Select = document.getElementById('compare-v2-select');

        const options = this.versionList.map(v =>
            `<option value="${v.id}">v${v.version} - ${new Date(v.created_at).toLocaleString('zh-CN')}</option>`
        ).join('');

        v1Select.innerHTML = options;
        v2Select.innerHTML = options;

        if (this.versionList.length >= 2) {
            v2Select.selectedIndex = 1;
        }

        document.getElementById('version-diff-result').innerHTML = '';
        openModal('version-compare-modal');
    }

    async executeCompare() {
        const v1 = document.getElementById('compare-v1-select')?.value;
        const v2 = document.getElementById('compare-v2-select')?.value;

        if (!v1 || !v2) {
            this.notify('请选择两个版本', 'error');
            return;
        }

        if (v1 === v2) {
            this.notify('请选择不同的版本', 'error');
            return;
        }

        try {
            const response = await fetch(`/api/versions/compare?v1=${v1}&v2=${v2}`);
            const data = await response.json();

            if (data.success) {
                this.renderDiffResult(data);
            } else {
                this.notify(data.error || '比较失败', 'error');
            }
        } catch (error) {
            console.error('版本比较失败:', error);
            this.notify('比较失败', 'error');
        }
    }

    renderDiffResult(compareData) {
        const container = document.getElementById('version-diff-result');
        if (!container) return;

        const diff = compareData.diff || [];
        const changedCount = compareData.changed_count || 0;

        let html = `<div class="diff-summary">
            <span class="diff-summary-text">共 ${diff.length} 个字段，${changedCount} 个发生变化</span>
            <span class="diff-summary-versions">
                v${compareData.v1.version} → v${compareData.v2.version}
            </span>
        </div>`;

        if (diff.length === 0) {
            html += '<div class="diff-empty">两个版本完全相同</div>';
        } else {
            html += '<div class="diff-fields">';
            diff.forEach(d => {
                if (d.changed) {
                    html += `
                    <div class="diff-field diff-field-changed">
                        <div class="diff-field-name">${this.escapeHtml(d.field)}</div>
                        <div class="diff-field-values">
                            <div class="diff-old">
                                <span class="diff-label">旧值</span>
                                <span class="diff-text">${this.escapeHtml(String(d.old || '').substring(0, 300))}</span>
                            </div>
                            <div class="diff-arrow">→</div>
                            <div class="diff-new">
                                <span class="diff-label">新值</span>
                                <span class="diff-text">${this.escapeHtml(String(d.new || '').substring(0, 300))}</span>
                            </div>
                        </div>
                    </div>`;
                } else {
                    html += `
                    <div class="diff-field diff-field-unchanged">
                        <div class="diff-field-name">${this.escapeHtml(d.field)}</div>
                        <span class="diff-unchanged-text">未变化</span>
                    </div>`;
                }
            });
            html += '</div>';
        }

        container.innerHTML = html;
    }

    openRollbackModal() {
        if (!this.versionSelectedId) {
            this.notify('请先选择一个版本', 'error');
            return;
        }

        const selectedVersion = this.versionList.find(v => v.id === this.versionSelectedId);
        if (!selectedVersion) return;

        this.versionPendingRollbackId = this.versionSelectedId;
        document.getElementById('rollback-remark').value = '';
        openModal('version-rollback-modal');
    }

    async executeRollback() {
        if (!this.versionPendingRollbackId) return;

        const remark = document.getElementById('rollback-remark')?.value || '';

        try {
            const response = await fetch('/api/versions/rollback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    version_id: this.versionPendingRollbackId,
                    remark: remark
                })
            });

            const data = await response.json();

            if (data.success) {
                this.notify(data.message || '回滚成功');
                closeModal('version-rollback-modal');
                this.searchVersions();
            } else {
                this.notify(data.error || '回滚失败', 'error');
            }
        } catch (error) {
            console.error('版本回滚失败:', error);
            this.notify('回滚失败', 'error');
        }
    }

    editVersionRemark(versionId, currentRemark) {
        this.versionRemarkEditId = versionId;
        document.getElementById('version-remark-input').value = currentRemark || '';
        openModal('version-remark-modal');
    }

    async saveVersionRemark() {
        if (!this.versionRemarkEditId) return;

        const remark = document.getElementById('version-remark-input')?.value || '';

        try {
            const response = await fetch(`/api/versions/${this.versionRemarkEditId}/remark`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ remark: remark })
            });

            const data = await response.json();

            if (data.success) {
                this.notify('备注已更新');
                closeModal('version-remark-modal');
                this.searchVersions();
            } else {
                this.notify(data.error || '更新失败', 'error');
            }
        } catch (error) {
            console.error('备注更新失败:', error);
            this.notify('更新失败', 'error');
        }
    }

    async deleteVersion(versionId) {
        if (!confirm('确定要删除此版本吗？此操作不可恢复。')) return;

        try {
            const response = await fetch(`/api/versions/${versionId}`, { method: 'DELETE' });
            const data = await response.json();

            if (data.success) {
                this.notify('版本已删除');
                this.searchVersions();
            } else {
                this.notify(data.error || '删除失败', 'error');
            }
        } catch (error) {
            console.error('版本删除失败:', error);
            this.notify('删除失败', 'error');
        }
    }

    escapeAttr(str) {
        return str.replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ============ 工具函数 ============

    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    notify(message, type = 'success') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: ${type === 'error' ? '#EF4444' : '#22C55E'};
            color: white;
            border-radius: 6px;
            z-index: 9999;
            animation: slideIn 0.3s ease;
        `;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    // ============ 继续创作 ============

    async loadContinueCreating() {
        const grid = document.getElementById('cc-grid');
        if (!grid) return;

        try {
            const response = await fetch('/api/qrcodes/list');
            const data = await response.json();

            if (!data.success || !data.qrcodes || data.qrcodes.length === 0) {
                grid.innerHTML = `
                    <div class="cc-card cc-card-empty">
                        <div class="cc-empty-icon">📝</div>
                        <p class="cc-empty-text">暂无内容</p>
                        <p class="cc-empty-hint">点击上方"创建内容"开始你的第一个二维码</p>
                    </div>`;
                return;
            }

            const sorted = data.qrcodes
                .sort((a, b) => {
                    const dateA = a.updated_at || a.created_at || '';
                    const dateB = b.updated_at || b.created_at || '';
                    return dateB.localeCompare(dateA);
                })
                .slice(0, 5);

            grid.innerHTML = sorted.map(qr => {
                const title = qr.title || '未命名';
                const updatedAt = qr.updated_at || qr.created_at || '';
                const completion = this.estimateCompletion(qr);
                const relativeTime = this.formatRelativeTime(updatedAt);

                return `
                    <div class="cc-card" onclick="window.enterpriseApp.continueEdit(${qr.id})">
                        <div class="cc-card-title">${this.escapeHtml(title)}</div>
                        <div class="cc-card-meta">
                            <span class="cc-card-time">${relativeTime}</span>
                        </div>
                        <div class="cc-card-progress">
                            <div class="cc-progress-bar">
                                <div class="cc-progress-fill" style="width: ${completion}%"></div>
                            </div>
                            <span class="cc-progress-label">${completion}%</span>
                        </div>
                        <button class="cc-card-btn" onclick="event.stopPropagation(); window.enterpriseApp.continueEdit(${qr.id})">继续编辑</button>
                    </div>`;
            }).join('');
        } catch (error) {
            console.error('加载继续创作失败:', error);
            grid.innerHTML = `
                <div class="cc-card cc-card-empty">
                    <div class="cc-empty-icon">⚠️</div>
                    <p class="cc-empty-text">加载失败</p>
                    <p class="cc-empty-hint">请刷新页面重试</p>
                </div>`;
        }
    }

    estimateCompletion(qrcode) {
        let score = 0;

        if (qrcode.title && qrcode.title.trim() && qrcode.title !== '未命名') {
            score += 30;
        }
        if (qrcode.content && qrcode.content !== '{}') {
            score += 25;
        }
        if (qrcode.status && qrcode.status === 'active') {
            score += 15;
        }
        if (qrcode.scan_count && qrcode.scan_count > 0) {
            score += Math.min(15, qrcode.scan_count * 2);
        }
        if (qrcode.dynamic_links && qrcode.dynamic_links.length > 0) {
            score += 15;
        }

        if (score < 10) score = 10;
        return Math.min(100, Math.round(score));
    }

    formatRelativeTime(dateStr) {
        if (!dateStr) return '未知时间';

        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHour / 24);

        if (diffSec < 60) return '刚刚';
        if (diffMin < 60) return `${diffMin}分钟前`;
        if (diffHour < 24) return `${diffHour}小时前`;
        if (diffDay < 7) return `${diffDay}天前`;
        if (diffDay < 30) return `${Math.floor(diffDay / 7)}周前`;

        return date.toLocaleDateString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
    }

    continueEdit(qrcodeId) {
        window.location.href = `/?tab=generator&edit=${qrcodeId}`;
    }

    // ============ 通知中心 ============

    initNotificationCenter() {
        this.notifPage = 1;
        this.notifCategory = '';
        this.notifStatus = '';
        this.notifSearch = '';
        this.notifPollingTimer = null;
        this.notifWebhookEditId = null;

        document.getElementById('notif-read-all-btn')?.addEventListener('click', () => this.notifReadAll());
        document.getElementById('notif-settings-btn')?.addEventListener('click', () => this.openNotifSettings());
        document.getElementById('notif-refresh-btn')?.addEventListener('click', () => this.loadNotifications());
        document.getElementById('notif-search-input')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { this.notifSearch = e.target.value.trim(); this.notifPage = 1; this.loadNotifications(); }
        });
        document.getElementById('notif-settings-save')?.addEventListener('click', () => this.saveNotifSettings());
        document.getElementById('webhook-add-btn')?.addEventListener('click', () => this.showWebhookForm());
        document.getElementById('webhook-cancel-btn')?.addEventListener('click', () => this.hideWebhookForm());
        document.getElementById('webhook-save-btn')?.addEventListener('click', () => this.saveWebhook());

        document.querySelectorAll('.notif-category-item').forEach(el => {
            el.addEventListener('click', () => {
                document.querySelectorAll('.notif-category-item').forEach(e => e.classList.remove('active'));
                el.classList.add('active');
                this.notifCategory = el.dataset.category;
                this.notifPage = 1;
                this.loadNotifications();
            });
        });

        document.querySelectorAll('.notif-status-btn').forEach(el => {
            el.addEventListener('click', () => {
                document.querySelectorAll('.notif-status-btn').forEach(e => e.classList.remove('active'));
                el.classList.add('active');
                this.notifStatus = el.dataset.status;
                this.notifPage = 1;
                this.loadNotifications();
            });
        });

        this.startNotifPolling();
    }

    startNotifPolling() {
        this.fetchUnreadCount();
        this.notifPollingTimer = setInterval(() => this.fetchUnreadCount(), 30000);
    }

    async fetchUnreadCount() {
        try {
            const res = await fetch('/api/notifications/unread-count');
            const data = await res.json();
            if (data.success) {
                this.updateUnreadBadge(data.unread);
            }
        } catch (e) { /* 静默 */ }
    }

    updateUnreadBadge(unread) {
        const total = unread?.total || 0;
        const badge = document.getElementById('nav-notif-badge');
        if (badge) {
            if (total > 0) {
                badge.textContent = total > 99 ? '99+' : total;
                badge.style.display = 'inline-flex';
            } else {
                badge.style.display = 'none';
            }
        }
        if (unread) {
            for (const cat of Object.keys(unread)) {
                const el = document.getElementById(`notif-cat-${cat}`);
                if (el) {
                    const count = unread[cat] || 0;
                    el.textContent = count;
                    el.style.display = count > 0 ? '' : 'none';
                }
            }
        }
    }

    async loadNotifications() {
        try {
            const params = new URLSearchParams();
            params.set('page', this.notifPage);
            params.set('size', 20);
            if (this.notifCategory) params.set('category', this.notifCategory);
            if (this.notifStatus) params.set('status', this.notifStatus);
            if (this.notifSearch) params.set('q', this.notifSearch);

            const res = await fetch(`/api/notifications?${params}`);
            const data = await res.json();
            if (data.success) {
                this.renderNotifications(data);
            }
        } catch (e) {
            console.error('加载通知失败:', e);
        }
    }

    renderNotifications(data) {
        const container = document.getElementById('notif-list');
        if (!container) return;

        const notifications = data.notifications || [];

        if (notifications.length === 0) {
            container.innerHTML = `<div class="notif-empty"><div class="notif-empty-icon">📭</div><p>暂无通知</p></div>`;
        } else {
            container.innerHTML = notifications.map(n => {
                const time = this.formatTimeAgo(n.created_at);
                const isArchived = n.is_archived ? ' notif-item-archived' : '';
                return `
                <div class="notif-item${n.is_read ? '' : ' unread'}${isArchived}" data-id="${n.id}" onclick="window.enterpriseApp.notifClick(${n.id}, '${(n.link || '').replace(/'/g, "\\'")}')">
                    <div class="notif-item-icon" style="background:${n.category_color}20; color:${n.category_color}">${n.category_icon}</div>
                    <div class="notif-item-body">
                        <div class="notif-item-title">${this.escapeHtml(n.title)}</div>
                        ${n.content ? `<div class="notif-item-content">${this.escapeHtml(n.content)}</div>` : ''}
                        <div class="notif-item-meta">
                            <span class="notif-item-category" style="background:${n.category_color}15; color:${n.category_color}">${n.category_label}</span>
                            <span>${time}</span>
                        </div>
                    </div>
                    <div class="notif-item-actions">
                        ${n.is_read ? '' : `<button class="notif-item-action" title="标记已读" onclick="event.stopPropagation(); window.enterpriseApp.notifMarkRead(${n.id})">✓</button>`}
                        <button class="notif-item-action" title="${n.is_archived ? '取消归档' : '归档'}" onclick="event.stopPropagation(); window.enterpriseApp.notifArchive(${n.id}, ${!n.is_archived})">${n.is_archived ? '📂' : '📁'}</button>
                        <button class="notif-item-action delete" title="删除" onclick="event.stopPropagation(); window.enterpriseApp.notifDelete(${n.id})">🗑</button>
                    </div>
                    ${n.is_read ? '' : '<div class="notif-unread-dot"></div>'}
                </div>`;
            }).join('');
        }

        this.renderNotifPagination(data);
    }

    renderNotifPagination(data) {
        const container = document.getElementById('notif-pagination');
        if (!container) return;

        if (data.total_pages <= 1) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'flex';
        let html = `<button class="notif-page-btn" ${data.page <= 1 ? 'disabled' : ''} onclick="window.enterpriseApp.notifGoPage(${data.page - 1})">上一页</button>`;

        for (let i = 1; i <= data.total_pages; i++) {
            if (i === 1 || i === data.total_pages || Math.abs(i - data.page) <= 2) {
                html += `<button class="notif-page-btn${data.page === i ? ' active' : ''}" onclick="window.enterpriseApp.notifGoPage(${i})">${i}</button>`;
            } else if (Math.abs(i - data.page) === 3) {
                html += `<span class="notif-page-info">...</span>`;
            }
        }

        html += `<button class="notif-page-btn" ${data.page >= data.total_pages ? 'disabled' : ''} onclick="window.enterpriseApp.notifGoPage(${data.page + 1})">下一页</button>`;
        html += `<span class="notif-page-info">共 ${data.total} 条</span>`;
        container.innerHTML = html;
    }

    notifGoPage(page) {
        this.notifPage = page;
        this.loadNotifications();
    }

    notifClick(id, link) {
        this.notifMarkRead(id);
        if (link) {
            window.location.href = link;
        }
    }

    async notifMarkRead(id) {
        try {
            await fetch(`/api/notifications/${id}/read`, { method: 'PUT' });
            this.fetchUnreadCount();
            this.loadNotifications();
        } catch (e) { /* 静默 */ }
    }

    async notifReadAll() {
        try {
            const params = this.notifCategory ? `?category=${this.notifCategory}` : '';
            await fetch(`/api/notifications/read-all${params}`, { method: 'PUT' });
            this.fetchUnreadCount();
            this.loadNotifications();
            this.showToast('已全部标记为已读');
        } catch (e) {
            this.showToast('操作失败', 'error');
        }
    }

    async notifArchive(id, archive) {
        try {
            await fetch(`/api/notifications/${id}/archive`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ archive })
            });
            this.loadNotifications();
            this.showToast(archive ? '已归档' : '已取消归档');
        } catch (e) {
            this.showToast('操作失败', 'error');
        }
    }

    async notifDelete(id) {
        if (!confirm('确定删除这条通知？')) return;
        try {
            await fetch(`/api/notifications/${id}`, { method: 'DELETE' });
            this.fetchUnreadCount();
            this.loadNotifications();
            this.showToast('已删除');
        } catch (e) {
            this.showToast('删除失败', 'error');
        }
    }

    async openNotifSettings() {
        try {
            const res = await fetch('/api/notifications/settings');
            const data = await res.json();
            if (data.success) {
                this.renderNotifSettings(data.settings);
            }
            document.getElementById('notif-settings-modal').classList.add('active');
        } catch (e) {
            this.showToast('加载设置失败', 'error');
        }
    }

    renderNotifSettings(settings) {
        const table = document.getElementById('notif-settings-table');
        if (!table) return;

        let html = `<div class="notif-settings-row notif-settings-header">
            <span class="ns-category">通知类型</span>
            <span class="ns-channel">站内信</span>
            <span class="ns-channel">邮件</span>
            <span class="ns-channel">Webhook</span>
            <span class="ns-channel ns-disabled">短信</span>
            <span class="ns-channel ns-disabled">企业微信</span>
        </div>`;

        for (const [cat, s] of Object.entries(settings)) {
            html += `
            <div class="notif-settings-row">
                <span class="ns-category">${s.icon} ${s.label}</span>
                <span class="ns-channel"><input type="checkbox" data-cat="${cat}" data-channel="inapp" ${s.inapp ? 'checked' : ''}></span>
                <span class="ns-channel"><input type="checkbox" data-cat="${cat}" data-channel="email" ${s.email ? 'checked' : ''}></span>
                <span class="ns-channel"><input type="checkbox" data-cat="${cat}" data-channel="webhook" ${s.webhook ? 'checked' : ''}></span>
                <span class="ns-channel ns-disabled"><input type="checkbox" disabled></span>
                <span class="ns-channel ns-disabled"><input type="checkbox" disabled></span>
            </div>`;
        }

        table.innerHTML = html;
    }

    async saveNotifSettings() {
        const settings = {};
        document.querySelectorAll('#notif-settings-table input[type="checkbox"]:not(:disabled)').forEach(cb => {
            const cat = cb.dataset.cat;
            const channel = cb.dataset.channel;
            if (!settings[cat]) settings[cat] = {};
            settings[cat][channel] = cb.checked;
        });

        try {
            const res = await fetch('/api/notifications/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings })
            });
            const data = await res.json();
            if (data.success) {
                closeModal('notif-settings-modal');
                this.showToast('通知设置已保存');
            }
        } catch (e) {
            this.showToast('保存失败', 'error');
        }
    }

    async openWebhookModal() {
        try {
            const res = await fetch('/api/webhooks');
            const data = await res.json();
            if (data.success) {
                this.renderWebhooks(data.webhooks);
            }
            document.getElementById('webhook-modal').classList.add('active');
            this.hideWebhookForm();
        } catch (e) {
            this.showToast('加载Webhook失败', 'error');
        }
    }

    renderWebhooks(webhooks) {
        const container = document.getElementById('webhook-list');
        if (!container) return;

        if (webhooks.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-muted);">暂无Webhook配置</div>';
            return;
        }

        container.innerHTML = webhooks.map(w => `
            <div class="webhook-item">
                <div class="webhook-item-info">
                    <div class="webhook-item-name">${this.escapeHtml(w.name)}</div>
                    <div class="webhook-item-url">${this.escapeHtml(w.url)}</div>
                    <div class="webhook-item-meta">
                        <span class="webhook-status ${w.is_active ? 'active' : 'inactive'}">${w.is_active ? '● 启用' : '○ 停用'}</span>
                        <span>事件: ${(w.events || []).join(', ') || '全部'}</span>
                        ${w.last_triggered_at ? `<span>最后触发: ${w.last_triggered_at}</span>` : ''}
                    </div>
                </div>
                <div class="webhook-item-actions">
                    <button onclick="window.enterpriseApp.testWebhook(${w.id})">测试</button>
                    <button onclick="window.enterpriseApp.editWebhook(${w.id}, '${this.escapeHtml(w.name)}', '${this.escapeHtml(w.url)}', ${JSON.stringify(w.events || [])}, ${w.is_active})">编辑</button>
                    <button onclick="window.enterpriseApp.deleteWebhook(${w.id})" style="color:#EF4444;">删除</button>
                </div>
            </div>
        `).join('');
    }

    showWebhookForm(editData = null) {
        this.notifWebhookEditId = editData?.id || null;
        const form = document.getElementById('webhook-form');
        const title = document.getElementById('webhook-form-title');
        if (!form || !title) return;

        document.getElementById('webhook-name').value = editData?.name || '';
        document.getElementById('webhook-url').value = editData?.url || '';
        document.getElementById('webhook-secret').value = '';
        document.querySelectorAll('#webhook-events input[type="checkbox"]').forEach(cb => {
            cb.checked = editData?.events?.includes(cb.value) || false;
        });

        title.textContent = editData ? '编辑 Webhook' : '新建 Webhook';
        form.style.display = 'block';
    }

    hideWebhookForm() {
        const form = document.getElementById('webhook-form');
        if (form) form.style.display = 'none';
        this.notifWebhookEditId = null;
    }

    async saveWebhook() {
        const name = document.getElementById('webhook-name').value.trim();
        const url = document.getElementById('webhook-url').value.trim();
        const secret = document.getElementById('webhook-secret').value.trim();
        const events = Array.from(document.querySelectorAll('#webhook-events input[type="checkbox"]:checked')).map(cb => cb.value);

        if (!name || !url) { this.showToast('名称和URL不能为空', 'error'); return; }

        try {
            const body = { name, url, events };
            if (secret) body.secret = secret;

            let res;
            if (this.notifWebhookEditId) {
                res = await fetch(`/api/webhooks/${this.notifWebhookEditId}`, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
                });
            } else {
                res = await fetch('/api/webhooks', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
                });
            }

            const data = await res.json();
            if (data.success) {
                this.showToast(data.message);
                this.hideWebhookForm();
                this.openWebhookModal();
            } else {
                this.showToast(data.error || '保存失败', 'error');
            }
        } catch (e) {
            this.showToast('保存失败', 'error');
        }
    }

    editWebhook(id, name, url, events, isActive) {
        this.showWebhookForm({ id, name, url, events, isActive });
    }

    async deleteWebhook(id) {
        if (!confirm('确定删除此Webhook？')) return;
        try {
            await fetch(`/api/webhooks/${id}`, { method: 'DELETE' });
            this.showToast('Webhook已删除');
            this.openWebhookModal();
        } catch (e) {
            this.showToast('删除失败', 'error');
        }
    }

    async testWebhook(id) {
        try {
            const res = await fetch(`/api/webhooks/${id}/test`, { method: 'POST' });
            const data = await res.json();
            this.showToast(data.success ? '测试通知已发送' : (data.error || '测试失败'));
        } catch (e) {
            this.showToast('测试失败', 'error');
        }
    }

    formatTimeAgo(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr + (dateStr.endsWith('Z') ? '' : 'Z'));
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);

        if (diff < 60) return '刚刚';
        if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
        if (diff < 2592000) return `${Math.floor(diff / 86400)}天前`;
        return dateStr.substring(0, 10);
    }

    showToast(message, type = 'success') {
        const existing = document.querySelector('.toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position:fixed; bottom:24px; right:24px; padding:12px 24px;
            border-radius:8px; color:#fff; font-size:14px; z-index:10000;
            animation: toastIn 0.3s ease;
            background: ${type === 'error' ? '#EF4444' : '#22C55E'};
        `;
        document.body.appendChild(toast);
        setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s'; setTimeout(() => toast.remove(), 300); }, 3000);
    }

    // ============ 统一搜索中心 ============

    initSearchCenter() {
        this.searchPage = 1;
        this.searchQuery = '';
        this.searchType = '';
        this.searchOperator = 'AND';
        this.searchStatus = '';
        this.searchCreator = '';
        this.searchDateFrom = '';
        this.searchDateTo = '';
        this.searchTags = '';
        this.searchSuggestionTimer = null;
        this.searchHistoryPanel = false;
        this.searchSavedPanel = false;

        const input = document.getElementById('search-input');
        const btn = document.getElementById('search-btn');
        const typeSel = document.getElementById('search-type');
        const opSel = document.getElementById('search-operator');
        const statusSel = document.getElementById('search-status');
        const creatorSel = document.getElementById('search-creator');
        const dateFrom = document.getElementById('search-date-from');
        const dateTo = document.getElementById('search-date-to');
        const tagsInput = document.getElementById('search-tags');

        if (btn) btn.addEventListener('click', () => { this.searchPage = 1; this.doSearch(); });
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { this.searchPage = 1; this.doSearch(); }
            });
            input.addEventListener('input', () => {
                this.searchQuery = input.value.trim();
                this.searchPage = 1;
                clearTimeout(this.searchSuggestionTimer);
                if (this.searchQuery.length >= 1) {
                    this.searchSuggestionTimer = setTimeout(() => this.loadSearchSuggestions(), 200);
                } else {
                    const sug = document.getElementById('search-suggestions');
                    if (sug) sug.style.display = 'none';
                }
            });
            document.addEventListener('click', (e) => {
                const sug = document.getElementById('search-suggestions');
                const wrap = document.querySelector('.search-input-wrapper');
                if (sug && wrap && !wrap.contains(e.target)) sug.style.display = 'none';
            });
        }

        if (typeSel) {
            typeSel.addEventListener('change', () => {
                this.searchType = typeSel.value;
                this.updateStatusOptions();
                this.searchPage = 1;
            });
        }
        if (opSel) opSel.addEventListener('change', () => { this.searchOperator = opSel.value; });
        if (statusSel) statusSel.addEventListener('change', () => { this.searchStatus = statusSel.value; });
        if (creatorSel) creatorSel.addEventListener('change', () => { this.searchCreator = creatorSel.value; });
        if (dateFrom) dateFrom.addEventListener('change', () => { this.searchDateFrom = dateFrom.value; });
        if (dateTo) dateTo.addEventListener('change', () => { this.searchDateTo = dateTo.value; });
        if (tagsInput) tagsInput.addEventListener('change', () => { this.searchTags = tagsInput.value.trim(); });

        const advToggle = document.getElementById('search-advanced-toggle');
        if (advToggle) {
            advToggle.addEventListener('click', () => {
                const panel = document.getElementById('search-advanced');
                if (panel) {
                    const isOpen = panel.style.display !== 'none';
                    panel.style.display = isOpen ? 'none' : 'block';
                    advToggle.classList.toggle('open', !isOpen);
                }
            });
        }

        const histToggle = document.getElementById('search-history-toggle');
        if (histToggle) {
            histToggle.addEventListener('click', () => {
                this.searchHistoryPanel = !this.searchHistoryPanel;
                const panel = document.getElementById('search-history-panel');
                if (panel) panel.style.display = this.searchHistoryPanel ? 'block' : 'none';
                if (this.searchHistoryPanel) this.loadSearchHistory();
            });
        }

        const savedToggle = document.getElementById('search-saved-toggle');
        if (savedToggle) {
            savedToggle.addEventListener('click', () => {
                this.searchSavedPanel = !this.searchSavedPanel;
                const panel = document.getElementById('search-saved-panel');
                if (panel) panel.style.display = this.searchSavedPanel ? 'block' : 'none';
                if (this.searchSavedPanel) this.loadSavedSearches();
            });
        }

        const histClear = document.getElementById('search-history-clear');
        if (histClear) {
            histClear.addEventListener('click', () => this.clearSearchHistory());
        }

        const saveBtn = document.getElementById('search-save-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.showSearchSaveModal());
        }

        const saveConfirm = document.getElementById('search-save-confirm');
        if (saveConfirm) {
            saveConfirm.addEventListener('click', () => this.saveSearch());
        }

        this.loadCreatorOptions();
    }

    async doSearch() {
        this.searchQuery = document.getElementById('search-input')?.value.trim() || '';
        this.searchType = document.getElementById('search-type')?.value || '';
        this.searchOperator = document.getElementById('search-operator')?.value || 'AND';
        this.searchStatus = document.getElementById('search-status')?.value || '';
        this.searchCreator = document.getElementById('search-creator')?.value || '';
        this.searchDateFrom = document.getElementById('search-date-from')?.value || '';
        this.searchDateTo = document.getElementById('search-date-to')?.value || '';
        this.searchTags = document.getElementById('search-tags')?.value.trim() || '';

        const params = new URLSearchParams();
        if (this.searchQuery) params.set('q', this.searchQuery);
        if (this.searchType) params.set('type', this.searchType);
        if (this.searchOperator) params.set('operator', this.searchOperator);
        if (this.searchStatus) params.set('status', this.searchStatus);
        if (this.searchCreator) params.set('creator', this.searchCreator);
        if (this.searchDateFrom) params.set('date_from', this.searchDateFrom);
        if (this.searchDateTo) params.set('date_to', this.searchDateTo);
        if (this.searchTags) params.set('tags', this.searchTags);
        params.set('page', this.searchPage);
        params.set('size', '20');

        try {
            const res = await fetch(`/api/search?${params}`);
            const data = await res.json();
            if (data.success) {
                this.renderSearchResults(data);
                const saveBtn = document.getElementById('search-save-btn');
                if (saveBtn) saveBtn.style.display = this.searchQuery ? 'inline-block' : 'none';
            }
        } catch (e) {
            console.error('搜索失败:', e);
        }
    }

    renderSearchResults(data) {
        const container = document.getElementById('search-results');
        const countEl = document.getElementById('search-result-count');
        const pagEl = document.getElementById('search-pagination');
        if (!container) return;

        const results = data.results || [];
        const total = data.total || 0;

        if (countEl) {
            countEl.innerHTML = total > 0 ? `共找到 <strong>${total}</strong> 条结果` : '';
        }

        if (results.length === 0) {
            container.innerHTML = `<div class="search-empty"><div class="search-empty-icon">🔍</div><p>${total === 0 ? '未找到匹配结果' : '输入关键词开始搜索'}</p></div>`;
        } else {
            container.innerHTML = results.map(r => {
                const time = this.formatTimeAgo(r.created_at);
                return `
                <div class="search-result-item" data-id="${r.id}" data-type="${r.resource_type}">
                    <div class="search-result-icon" style="background:${r.resource_type_color}20; color:${r.resource_type_color}">${r.resource_type_icon}</div>
                    <div class="search-result-body">
                        <div class="search-result-title">${this.escapeHtml(r.title)}</div>
                        <div class="search-result-meta">
                            <span class="search-result-type" style="background:${r.resource_type_color}15; color:${r.resource_type_color}">${r.resource_type_icon} ${r.resource_type_label}</span>
                            ${r.status_label ? `<span class="search-result-status">${this.escapeHtml(r.status_label)}</span>` : ''}
                            <span>${time}</span>
                        </div>
                    </div>
                </div>`;
            }).join('');
        }

        this.renderSearchPagination(data);
    }

    renderSearchPagination(data) {
        const pagEl = document.getElementById('search-pagination');
        if (!pagEl) return;
        if (data.total_pages <= 1) { pagEl.style.display = 'none'; return; }
        pagEl.style.display = 'flex';

        let html = '';
        html += `<button ${data.page <= 1 ? 'disabled' : ''} onclick="enterpriseApp.searchPage=${data.page - 1}; enterpriseApp.doSearch();">上一页</button>`;

        const start = Math.max(1, data.page - 2);
        const end = Math.min(data.total_pages, data.page + 2);
        for (let i = start; i <= end; i++) {
            html += `<button class="${i === data.page ? 'active' : ''}" onclick="enterpriseApp.searchPage=${i}; enterpriseApp.doSearch();">${i}</button>`;
        }

        html += `<button ${data.page >= data.total_pages ? 'disabled' : ''} onclick="enterpriseApp.searchPage=${data.page + 1}; enterpriseApp.doSearch();">下一页</button>`;
        html += `<span>共 ${data.total_pages} 页</span>`;
        pagEl.innerHTML = html;
    }

    async loadSearchSuggestions() {
        const q = this.searchQuery;
        if (!q) return;

        try {
            const res = await fetch(`/api/search/suggestions?q=${encodeURIComponent(q)}`);
            const data = await res.json();
            if (!data.success || !data.suggestions || data.suggestions.length === 0) {
                document.getElementById('search-suggestions').style.display = 'none';
                return;
            }

            const sug = document.getElementById('search-suggestions');
            sug.innerHTML = data.suggestions.map(s => {
                const icon = s.source === 'history' ? '🕐' : '🔥';
                return `<div class="search-suggestion-item" onclick="enterpriseApp.selectSuggestion('${this.escapeAttr(s.keyword)}')"><span class="sug-icon">${icon}</span>${this.escapeHtml(s.keyword)}</div>`;
            }).join('');
            sug.style.display = 'block';
        } catch (e) {
            console.error('搜索建议失败:', e);
        }
    }

    selectSuggestion(keyword) {
        const input = document.getElementById('search-input');
        if (input) input.value = keyword;
        document.getElementById('search-suggestions').style.display = 'none';
        this.searchQuery = keyword;
        this.searchPage = 1;
        this.doSearch();
    }

    async loadSearchHistory() {
        try {
            const res = await fetch('/api/search/history');
            const data = await res.json();
            const list = document.getElementById('search-history-list');
            if (!list) return;

            if (!data.history || data.history.length === 0) {
                list.innerHTML = '<span style="font-size:13px;color:var(--text-secondary)">暂无搜索历史</span>';
                return;
            }

            list.innerHTML = data.history.map(h => {
                const typeLabel = h.resource_type ? ` · ${h.resource_type}` : '';
                return `<span class="search-history-item" onclick="enterpriseApp.selectHistory('${this.escapeAttr(h.keyword)}', '${this.escapeAttr(h.resource_type || '')}')">${this.escapeHtml(h.keyword)}${typeLabel}</span>`;
            }).join('');
        } catch (e) {
            console.error('加载搜索历史失败:', e);
        }
    }

    selectHistory(keyword, type) {
        const input = document.getElementById('search-input');
        if (input) input.value = keyword;
        const typeSel = document.getElementById('search-type');
        if (typeSel && type) typeSel.value = type;
        this.searchQuery = keyword;
        this.searchType = type;
        this.searchPage = 1;
        this.doSearch();
    }

    async clearSearchHistory() {
        try {
            await fetch('/api/search/history', { method: 'DELETE' });
            this.loadSearchHistory();
            this.showToast('搜索历史已清除');
        } catch (e) {
            console.error('清除搜索历史失败:', e);
        }
    }

    async loadSavedSearches() {
        try {
            const res = await fetch('/api/search/saved');
            const data = await res.json();
            const list = document.getElementById('search-saved-list');
            if (!list) return;

            if (!data.saved || data.saved.length === 0) {
                list.innerHTML = '<span style="font-size:13px;color:var(--text-secondary)">暂无已保存的搜索</span>';
                return;
            }

            list.innerHTML = data.saved.map(s => {
                const q = s.query.q || '';
                const type = s.query.type || '';
                const typeLabel = type ? SEARCH_RESOURCE_LABELS[type] || type : '';
                return `<span class="search-saved-item" onclick="enterpriseApp.applySavedSearch('${this.escapeAttr(JSON.stringify(s.query))}')">${this.escapeHtml(s.name)} (${q ? this.escapeHtml(q) : typeLabel || '全部'})<span class="saved-delete" onclick="event.stopPropagation(); enterpriseApp.deleteSavedSearch(${s.id})">✕</span></span>`;
            }).join('');
        } catch (e) {
            console.error('加载已保存搜索失败:', e);
        }
    }

    applySavedSearch(queryJson) {
        try {
            const q = typeof queryJson === 'string' ? JSON.parse(queryJson) : queryJson;
            if (q.q) { document.getElementById('search-input').value = q.q; this.searchQuery = q.q; }
            if (q.type) { document.getElementById('search-type').value = q.type; this.searchType = q.type; this.updateStatusOptions(); }
            if (q.operator) { document.getElementById('search-operator').value = q.operator; this.searchOperator = q.operator; }
            if (q.status) { document.getElementById('search-status').value = q.status; this.searchStatus = q.status; }
            if (q.creator) { document.getElementById('search-creator').value = q.creator; this.searchCreator = q.creator; }
            if (q.date_from) { document.getElementById('search-date-from').value = q.date_from; this.searchDateFrom = q.date_from; }
            if (q.date_to) { document.getElementById('search-date-to').value = q.date_to; this.searchDateTo = q.date_to; }
            if (q.tags) { document.getElementById('search-tags').value = q.tags; this.searchTags = q.tags; }
            this.searchPage = 1;
            this.doSearch();
        } catch (e) {
            console.error('应用已保存搜索失败:', e);
        }
    }

    async deleteSavedSearch(id) {
        try {
            await fetch(`/api/search/saved/${id}`, { method: 'DELETE' });
            this.loadSavedSearches();
            this.showToast('搜索已删除');
        } catch (e) {
            console.error('删除已保存搜索失败:', e);
        }
    }

    showSearchSaveModal() {
        document.getElementById('search-save-name').value = '';
        openModal('search-save-modal');
    }

    async saveSearch() {
        const name = document.getElementById('search-save-name').value.trim();
        if (!name) { this.showToast('请输入搜索名称'); return; }

        const query = {
            q: this.searchQuery,
            type: this.searchType,
            operator: this.searchOperator,
            status: this.searchStatus,
            creator: this.searchCreator,
            date_from: this.searchDateFrom,
            date_to: this.searchDateTo,
            tags: this.searchTags
        };

        try {
            const res = await fetch('/api/search/saved', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, query })
            });
            const data = await res.json();
            if (data.success) {
                closeModal('search-save-modal');
                this.showToast('搜索已保存');
            } else {
                this.showToast(data.error || '保存失败');
            }
        } catch (e) {
            console.error('保存搜索失败:', e);
        }
    }

    updateStatusOptions() {
        const statusSel = document.getElementById('search-status');
        const type = this.searchType;
        if (!statusSel) return;

        let options = '<option value="">不限</option>';
        if (type === 'qrcode') {
            options += '<option value="normal">正常</option><option value="disabled">已禁用</option><option value="expired">已过期</option><option value="archived">已归档</option>';
        } else if (type === 'form') {
            options += '<option value="active">启用</option><option value="draft">草稿</option><option value="archived">已归档</option>';
        } else if (type === 'workorder') {
            options += '<option value="open">待处理</option><option value="in_progress">处理中</option><option value="resolved">已解决</option><option value="closed">已关闭</option>';
        } else if (type === 'inspection') {
            options += '<option value="normal">正常</option><option value="abnormal">异常</option><option value="pending">待处理</option>';
        } else if (type === 'user') {
            options += '<option value="1">启用</option><option value="0">禁用</option>';
        } else if (type === 'notification') {
            options += '<option value="0">未读</option><option value="1">已读</option>';
        }
        statusSel.innerHTML = options;
    }

    async loadCreatorOptions() {
        try {
            const res = await fetch('/api/users');
            const data = await res.json();
            const sel = document.getElementById('search-creator');
            if (!sel || !data.users) return;

            let options = '<option value="">不限</option>';
            data.users.forEach(u => {
                options += `<option value="${u.id}">${this.escapeHtml(u.username || u.email)}</option>`;
            });
            sel.innerHTML = options;
        } catch (e) {
            console.error('加载用户列表失败:', e);
        }
    }

    // ============ 批量操作中心 ============

    initBatchCenter() {
        this.batchPage = 1;
        this.batchStatusFilter = '';
        this.batchPollingTimer = null;

        const submitBtn = document.getElementById('batch-submit-btn');
        if (submitBtn) submitBtn.addEventListener('click', () => this.createBatchTask());

        const refreshBtn = document.getElementById('batch-refresh-btn');
        if (refreshBtn) refreshBtn.addEventListener('click', () => this.loadBatchTasks());

        const statusFilter = document.getElementById('batch-status-filter');
        if (statusFilter) {
            statusFilter.addEventListener('change', () => {
                this.batchStatusFilter = statusFilter.value;
                this.batchPage = 1;
                this.loadBatchTasks();
            });
        }

        const taskTypeSel = document.getElementById('batch-task-type');
        if (taskTypeSel) {
            taskTypeSel.addEventListener('change', () => this.updateBatchExtraFields());
        }
    }

    updateBatchExtraFields() {
        const taskType = document.getElementById('batch-task-type')?.value;
        const extraFields = document.getElementById('batch-extra-fields');
        const toggleGroup = document.getElementById('batch-toggle-group');
        const tagGroup = document.getElementById('batch-tag-group');

        if (!extraFields) return;
        if (taskType === 'toggle') {
            extraFields.style.display = 'flex';
            if (toggleGroup) toggleGroup.style.display = 'block';
            if (tagGroup) tagGroup.style.display = 'none';
        } else if (taskType === 'tag') {
            extraFields.style.display = 'flex';
            if (toggleGroup) toggleGroup.style.display = 'none';
            if (tagGroup) tagGroup.style.display = 'block';
        } else {
            extraFields.style.display = 'none';
        }
    }

    async createBatchTask() {
        const resourceType = document.getElementById('batch-resource-type')?.value || '';
        const taskType = document.getElementById('batch-task-type')?.value || '';
        const idsText = document.getElementById('batch-resource-ids')?.value || '';

        const ids = idsText.split(/[,\n]/).map(s => parseInt(s.trim())).filter(n => !isNaN(n) && n > 0);

        if (ids.length === 0) { this.showToast('请输入有效的资源ID', 'error'); return; }
        if (ids.length > 10000) { this.showToast('单次最多操作10000条数据', 'error'); return; }

        const payload = {
            resource_type: resourceType,
            task_type: taskType,
            resource_ids: ids,
            max_retries: 3
        };

        if (taskType === 'toggle') {
            payload.target_state = parseInt(document.getElementById('batch-target-state')?.value || '1');
        }
        if (taskType === 'tag') {
            payload.tag = document.getElementById('batch-tag-value')?.value || '';
        }

        try {
            const res = await fetch('/api/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.success) {
                this.showToast(`批量任务已创建 (ID: ${data.task_id})`);
                document.getElementById('batch-resource-ids').value = '';
                this.loadBatchTasks();
                this.startBatchPolling(data.task_id);
            } else {
                this.showToast(data.error || '创建失败', 'error');
            }
        } catch (e) {
            console.error('创建批量任务失败:', e);
            this.showToast('创建失败', 'error');
        }
    }

    async loadBatchTasks() {
        try {
            const params = new URLSearchParams();
            params.set('page', this.batchPage);
            params.set('size', '20');
            if (this.batchStatusFilter) params.set('status', this.batchStatusFilter);

            const res = await fetch(`/api/batch?${params}`);
            const data = await res.json();
            if (data.success) {
                this.renderBatchTasks(data);
            }
        } catch (e) {
            console.error('加载批量任务失败:', e);
        }
    }

    renderBatchTasks(data) {
        const container = document.getElementById('batch-tasks-list');
        if (!container) return;

        const tasks = data.tasks || [];
        if (tasks.length === 0) {
            container.innerHTML = '<div class="batch-empty">暂无批量任务</div>';
        } else {
            container.innerHTML = tasks.map(t => {
                const statusColor = this.getBatchStatusColor(t.status);
                const statusLabel = this.getBatchStatusLabel(t.status);
                const fillClass = t.status === 'completed' ? 'success' : t.status === 'failed' ? 'failed' : '';
                const time = this.formatTimeAgo(t.created_at);
                return `
                <div class="batch-task-item" onclick="enterpriseApp.openBatchDetail(${t.id})">
                    <div class="batch-task-header">
                        <div class="batch-task-title">
                            <span class="batch-task-type-badge" style="background:${t.task_type_color}15; color:${t.task_type_color}">${t.task_type_icon} ${t.task_type_label}</span>
                            <span>${this.escapeHtml(t.resource_type)}</span>
                        </div>
                        <span class="batch-task-status" style="background:${statusColor}15; color:${statusColor}">${statusLabel}</span>
                    </div>
                    <div class="batch-progress-mini">
                        <div class="batch-progress-mini-fill ${fillClass}" style="width:${t.progress}%"></div>
                    </div>
                    <div class="batch-task-stats">
                        <span>📊 总计: ${t.total_count}</span>
                        <span>✅ 成功: ${t.success_count}</span>
                        <span>❌ 失败: ${t.fail_count}</span>
                        <span style="margin-left:auto">${time}</span>
                    </div>
                </div>`;
            }).join('');
        }

        this.renderBatchPagination(data);
    }

    renderBatchPagination(data) {
        const pagEl = document.getElementById('batch-pagination');
        if (!pagEl) return;
        if (data.total_pages <= 1) { pagEl.style.display = 'none'; return; }
        pagEl.style.display = 'flex';

        let html = '';
        html += `<button ${data.page <= 1 ? 'disabled' : ''} onclick="enterpriseApp.batchPage=${data.page - 1}; enterpriseApp.loadBatchTasks();">上一页</button>`;
        const start = Math.max(1, data.page - 2);
        const end = Math.min(data.total_pages, data.page + 2);
        for (let i = start; i <= end; i++) {
            html += `<button class="${i === data.page ? 'active' : ''}" onclick="enterpriseApp.batchPage=${i}; enterpriseApp.loadBatchTasks();">${i}</button>`;
        }
        html += `<button ${data.page >= data.total_pages ? 'disabled' : ''} onclick="enterpriseApp.batchPage=${data.page + 1}; enterpriseApp.loadBatchTasks();">下一页</button>`;
        pagEl.innerHTML = html;
    }

    async openBatchDetail(taskId) {
        this.batchDetailTaskId = taskId;
        openModal('batch-detail-modal');
        await this.loadBatchDetail();
        this.startBatchPolling(taskId);
    }

    async loadBatchDetail() {
        const taskId = this.batchDetailTaskId;
        if (!taskId) return;

        try {
            const res = await fetch(`/api/batch/${taskId}`);
            const data = await res.json();
            if (!data.success) return;

            const task = data.task;
            const items = data.items || [];

            const statusColor = this.getBatchStatusColor(task.status);
            const statusLabel = this.getBatchStatusLabel(task.status);
            const progressClass = task.status === 'completed' ? 'completed' : task.status === 'failed' ? 'failed' : '';

            document.getElementById('batch-detail-info').innerHTML = `
                <div class="info-item"><span class="info-label">任务ID</span><span class="info-value">#${task.id}</span></div>
                <div class="info-item"><span class="info-label">操作类型</span><span class="info-value">${task.task_type}</span></div>
                <div class="info-item"><span class="info-label">资源类型</span><span class="info-value">${task.resource_type}</span></div>
                <div class="info-item"><span class="info-label">状态</span><span class="info-value" style="color:${statusColor}">${statusLabel}</span></div>
                <div class="info-item"><span class="info-label">创建时间</span><span class="info-value">${task.created_at}</span></div>
            `;

            document.getElementById('batch-progress-fill').style.width = `${task.progress}%`;
            document.getElementById('batch-progress-fill').className = `batch-progress-fill ${progressClass}`;
            document.getElementById('batch-progress-text').textContent = `${task.progress}%`;

            document.getElementById('batch-detail-stats').innerHTML = `
                <div class="batch-stat-card"><div class="batch-stat-value total">${task.total_count}</div><div class="batch-stat-label">总计</div></div>
                <div class="batch-stat-card"><div class="batch-stat-value success">${task.success_count}</div><div class="batch-stat-label">成功</div></div>
                <div class="batch-stat-card"><div class="batch-stat-value fail">${task.fail_count}</div><div class="batch-stat-label">失败</div></div>
            `;

            let itemsHtml = '<div class="batch-items-row batch-items-header"><span>ID</span><span>标题</span><span>状态</span><span>操作</span></div>';
            items.forEach(item => {
                const itemStatusClass = item.status === 'success' ? 'success' : 'failed';
                const itemStatusLabel = item.status === 'success' ? '成功' : '失败';
                itemsHtml += `
                <div class="batch-items-row">
                    <span>#${item.resource_id}</span>
                    <span>${this.escapeHtml(item.title || '')}</span>
                    <span class="batch-item-status ${itemStatusClass}">${itemStatusLabel}</span>
                    <span>${item.action}</span>
                </div>`;
            });
            document.getElementById('batch-items-table').innerHTML = itemsHtml;

            let actionsHtml = '';
            if (task.status === 'running' || task.status === 'pending') {
                actionsHtml += `<button class="btn-secondary" onclick="enterpriseApp.cancelBatchTask(${task.id})">⏹ 取消任务</button>`;
            }
            if (task.status === 'completed') {
                actionsHtml += `<button class="btn-outline" onclick="enterpriseApp.rollbackBatchTask(${task.id})">↩ 回滚</button>`;
                actionsHtml += `<button class="btn-outline" onclick="window.open('/api/batch/${task.id}/export')">📥 导出CSV</button>`;
            }
            if (task.status === 'failed') {
                actionsHtml += `<button class="btn-outline" onclick="window.open('/api/batch/${task.id}/export')">📥 导出CSV</button>`;
            }
            document.getElementById('batch-detail-actions').innerHTML = actionsHtml;

            if (task.status === 'running' || task.status === 'pending') {
                this.startBatchPolling(taskId);
            } else {
                this.stopBatchPolling();
            }
        } catch (e) {
            console.error('加载批量任务详情失败:', e);
        }
    }

    async cancelBatchTask(taskId) {
        try {
            const res = await fetch(`/api/batch/${taskId}/cancel`, { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                this.showToast('任务已取消');
                this.loadBatchDetail();
                this.loadBatchTasks();
            } else {
                this.showToast(data.error || '取消失败', 'error');
            }
        } catch (e) {
            console.error('取消批量任务失败:', e);
        }
    }

    async rollbackBatchTask(taskId) {
        if (!confirm('确定要回滚此任务吗？这将恢复所有已修改的数据到操作前的状态。')) return;

        try {
            const res = await fetch(`/api/batch/${taskId}/rollback`, { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                this.showToast(data.message);
                this.loadBatchDetail();
                this.loadBatchTasks();
            } else {
                this.showToast(data.error || '回滚失败', 'error');
            }
        } catch (e) {
            console.error('回滚批量任务失败:', e);
        }
    }

    startBatchPolling(taskId) {
        this.stopBatchPolling();
        this.batchPollingTimer = setInterval(async () => {
            try {
                const res = await fetch(`/api/batch/${taskId}`);
                const data = await res.json();
                if (!data.success || !data.task) return;
                const status = data.task.status;
                if (status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'rolled_back') {
                    this.stopBatchPolling();
                    await this.loadBatchDetail();
                    await this.loadBatchTasks();
                } else {
                    document.getElementById('batch-progress-fill').style.width = `${data.task.progress}%`;
                    document.getElementById('batch-progress-text').textContent = `${data.task.progress}%`;
                }
            } catch (e) {}
        }, 2000);
    }

    stopBatchPolling() {
        if (this.batchPollingTimer) {
            clearInterval(this.batchPollingTimer);
            this.batchPollingTimer = null;
        }
    }

    getBatchStatusColor(status) {
        const map = {
            'pending': '#F59E0B', 'running': '#38BDF8', 'completed': '#22C55E',
            'failed': '#EF4444', 'cancelled': '#6B7280', 'rolled_back': '#8B5CF6'
        };
        return map[status] || '#6B7280';
    }

    getBatchStatusLabel(status) {
        const map = {
            'pending': '待执行', 'running': '执行中', 'completed': '已完成',
            'failed': '已失败', 'cancelled': '已取消', 'rolled_back': '已回滚'
        };
        return map[status] || status;
    }

    closeBatchDetail() {
        this.stopBatchPolling();
        closeModal('batch-detail-modal');
    }

}

// ============ 全局函数 ============

let app;

const SEARCH_RESOURCE_LABELS = {
    qrcode: '二维码', file: '文件', form: '表单', workorder: '工单',
    inspection: '巡检', user: '用户', notification: '通知'
};

function switchAuthTab(tab) {
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    document.getElementById(`${tab}-tab`).classList.add('active');
}

function openModal(modalId) {
    document.getElementById(modalId).classList.add('active');
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.enterpriseApp = new SmartCodeEnterprise();
});