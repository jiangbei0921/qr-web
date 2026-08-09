// 上传框模板（3类型共用）
`<div class="upload-box" id="upload-box">
    <input type="file" id="file-input" onchange="...">
    <p class="upload-info" id="upload-info"></p>
</div>`

// 动态配置（仅 1 份，按类型切换）
const uploadCfg = {
    file:   { accept: '.zip,.doc,.docx,.pdf,...', info: '...单个最大 500MB' },
    image:  { accept: 'image/png,...', info: '...单张最大 500MB', multiple: 'multiple' },
    media:  { accept: 'video/mp4,...', info: '...最大 20GB' }
};
