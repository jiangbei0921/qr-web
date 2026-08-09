/**
 * 智码云 - 二维码多终端预览中心
 * 二维码渲染器（Canvas 实时渲染）
 */
class QRRenderer {
    constructor() {
        this.canvas = null;
        this.ctx = null;
    }

    /**
     * 初始化 Canvas
     */
    init(parentElement) {
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'preview-center__qr-canvas';
        this.ctx = this.canvas.getContext('2d');
        parentElement.appendChild(this.canvas);
    }

    /**
     * 根据数据渲染二维码
     * @param {Object} qrData - 二维码数据 { content, style_config }
     */
    render(qrData) {
        if (!this.canvas || !qrData) return;

        const content = this._extractContent(qrData);
        if (!content) {
            this._renderPlaceholder('无二维码内容');
            return;
        }

        const style = qrData.style_config || {};
        const fgColor = style.fill_color || '#000000';
        const bgColor = style.back_color || '#FFFFFF';
        const errorLevel = (style.error_correction || 'M').toUpperCase();

        const errorMap = {
            'L': QRCode.CorrectLevel.L,
            'M': QRCode.CorrectLevel.M,
            'Q': QRCode.CorrectLevel.Q,
            'H': QRCode.CorrectLevel.H
        };

        const parentWidth = this.canvas.parentElement.clientWidth;
        const parentHeight = this.canvas.parentElement.clientHeight;
        const maxSize = Math.min(parentWidth, parentHeight) * 0.85;

        try {
            this.canvas.width = maxSize;
            this.canvas.height = maxSize;

            if (typeof QRCode === 'undefined') {
                this._renderPlaceholder('QRCode 库未加载');
                return;
            }

            const qr = new QRCode(this.canvas, {
                text: content,
                width: maxSize,
                height: maxSize,
                colorDark: fgColor,
                colorLight: bgColor,
                correctLevel: errorMap[errorLevel] || QRCode.CorrectLevel.M
            });
        } catch (e) {
            console.error('二维码渲染失败:', e);
            this._renderPlaceholder('渲染失败');
        }
    }

    /**
     * 从二维码数据中提取实际内容
     */
    _extractContent(qrData) {
        if (qrData.qr_url) return qrData.qr_url;
        if (qrData.content_json && qrData.content_json.content) {
            return qrData.content_json.content;
        }
        if (qrData.content_json && qrData.content_json.url) {
            return qrData.content_json.url;
        }
        return typeof qrData.content_json === 'string'
            ? qrData.content_json
            : JSON.stringify(qrData.content_json || '');
    }

    _renderPlaceholder(text) {
        if (!this.ctx) return;
        const w = this.canvas.parentElement.clientWidth;
        const h = this.canvas.parentElement.clientHeight;
        this.canvas.width = w;
        this.canvas.height = h;
        this.ctx.fillStyle = '#e9ecef';
        this.ctx.fillRect(0, 0, w, h);
        this.ctx.fillStyle = '#6c757d';
        this.ctx.font = '14px sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.fillText(text, w / 2, h / 2);
    }

    /**
     * 清除 Canvas
     */
    clear() {
        if (this.ctx) {
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        }
    }

    /**
     * 销毁
     */
    destroy() {
        if (this.canvas && this.canvas.parentElement) {
            this.canvas.parentElement.removeChild(this.canvas);
        }
        this.canvas = null;
        this.ctx = null;
    }
}