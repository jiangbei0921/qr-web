/**
 * 智码云 - 二维码多终端预览中心
 * PDF 导出服务（基于 jsPDF）
 */
class PDFService {
    constructor() {
        this._jsPDFLoaded = false;
    }

    /**
     * 确保 jsPDF 已加载
     */
    async _ensureLib() {
        if (this._jsPDFLoaded) return;
        if (typeof jspdf !== 'undefined' && typeof jspdf.jsPDF !== 'undefined') {
            this._jsPDFLoaded = true;
            return;
        }
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/jspdf@2.5.2/dist/jspdf.umd.min.js';
            script.onload = () => { this._jsPDFLoaded = true; resolve(); };
            script.onerror = () => reject(new Error('jsPDF 加载失败'));
            document.head.appendChild(script);
        });
    }

    /**
     * 导出 PDF
     * @param {HTMLElement} element - 要导出的元素
     * @param {Object} options
     */
    async exportPDF(element, options = {}) {
        await this._ensureLib();
        const { jsPDF } = jspdf;

        const pageSize = options.pageSize || 'a4';
        const orientation = options.orientation || 'portrait';
        const title = options.title || '二维码预览';
        const includeMeta = options.includeMeta !== false;

        const doc = new jsPDF({ orientation, unit: 'mm', format: pageSize });

        const pageWidth = doc.internal.pageSize.getWidth();
        const pageHeight = doc.internal.pageSize.getHeight();

        const canvas = await html2canvas(element, {
            useCORS: true,
            allowTaint: true,
            backgroundColor: '#ffffff',
            scale: 2,
            logging: false
        });

        const imgData = canvas.toDataURL('image/png');

        const imgWidth = pageWidth - 20;
        const imgHeight = (canvas.height * imgWidth) / canvas.width;

        const x = 10;
        let y = 15;

        if (imgHeight > pageHeight - 30) {
            const scale = (pageHeight - 30) / imgHeight;
            const scaledWidth = imgWidth * scale;
            const scaledHeight = imgHeight * scale;
            const sx = (pageWidth - scaledWidth) / 2;
            doc.addImage(imgData, 'PNG', sx, y, scaledWidth, scaledHeight);
        } else {
            doc.addImage(imgData, 'PNG', x, y, imgWidth, imgHeight);
        }

        if (includeMeta) {
            const metaY = pageHeight - 18;
            doc.setFontSize(8);
            doc.setTextColor(128, 128, 128);
            doc.text(`标题: ${title}`, 10, metaY);
            doc.text(`导出时间: ${new Date().toLocaleString('zh-CN')}`, 10, metaY + 4);
            doc.text('由 SmartCode 智码云生成', 10, metaY + 8);

            const rightX = pageWidth - 10;
            doc.setFontSize(8);
            doc.text('SmartCode', rightX, metaY + 8, { align: 'right' });
        }

        const filename = `${title.replace(/[\\/:*?"<>|]/g, '_')}-preview-${Date.now()}.pdf`;
        doc.save(filename);
    }
}