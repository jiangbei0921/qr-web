/**
 * 智码云 - 二维码多终端预览中心
 * 截图服务（基于 html2canvas）
 */
class CaptureService {
    constructor() {
        this._html2canvasLoaded = false;
    }

    /**
     * 确保 html2canvas 已加载
     */
    async _ensureLib() {
        if (this._html2canvasLoaded) return;
        if (typeof html2canvas !== 'undefined') {
            this._html2canvasLoaded = true;
            return;
        }
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js';
            script.onload = () => { this._html2canvasLoaded = true; resolve(); };
            script.onerror = () => reject(new Error('html2canvas 加载失败'));
            document.head.appendChild(script);
        });
    }

    /**
     * 截图
     * @param {HTMLElement} element - 要截图的元素
     * @param {Object} options
     * @returns {Promise<Blob>}
     */
    async capture(element, options = {}) {
        await this._ensureLib();
        const format = options.format || 'png';
        const quality = options.quality || 92;

        const canvas = await html2canvas(element, {
            useCORS: true,
            allowTaint: true,
            backgroundColor: null,
            scale: options.scale || 2,
            logging: false
        });

        const mimeType = format === 'jpeg' ? 'image/jpeg' : 'image/png';
        return new Promise(resolve => {
            canvas.toBlob(blob => resolve(blob), mimeType, quality / 100);
        });
    }

    /**
     * 截图并下载
     */
    async captureAndDownload(element, filename, options = {}) {
        const blob = await this.capture(element, options);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /**
     * 显示截图闪光效果
     */
    static flash(element) {
        const flash = document.createElement('div');
        flash.className = 'preview-center__screenshot-flash';
        element.appendChild(flash);
        setTimeout(() => {
            if (flash.parentElement) flash.parentElement.removeChild(flash);
        }, 400);
    }
}