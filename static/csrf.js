/* 全局 CSRF 防护：自动为状态变更请求附加 X-CSRFToken 头 */
(function () {
  var meta = document.querySelector('meta[name="csrf-token"]');
  window.CSRF_TOKEN = meta ? meta.getAttribute('content') : '';

  var UNSAFE = ['POST', 'PUT', 'DELETE', 'PATCH'];

  function applyToken(init) {
    init = init || {};
    var method = (init.method || 'GET').toUpperCase();
    if (UNSAFE.indexOf(method) === -1) return init;
    init.headers = init.headers || {};
    var hasToken = Object.keys(init.headers).some(function (k) {
      return String(k).toLowerCase() === 'x-csrftoken';
    });
    if (!hasToken && window.CSRF_TOKEN) {
      init.headers['X-CSRFToken'] = window.CSRF_TOKEN;
    }
    return init;
  }

  var nativeFetch = window.fetch;
  if (nativeFetch) {
    window.fetch = function (input, init) {
      return nativeFetch.call(this, input, applyToken(init));
    };
  }

  var NativeXHR = window.XMLHttpRequest;
  if (NativeXHR) {
    var origOpen = NativeXHR.prototype.open;
    NativeXHR.prototype.open = function (method) {
      this.__csrfMethod = method;
      return origOpen.apply(this, arguments);
    };
    var origSend = NativeXHR.prototype.send;
    NativeXHR.prototype.send = function (body) {
      if (this.__csrfMethod && UNSAFE.indexOf(String(this.__csrfMethod).toUpperCase()) !== -1 && window.CSRF_TOKEN) {
        try { this.setRequestHeader('X-CSRFToken', window.CSRF_TOKEN); } catch (e) {}
      }
      return origSend.apply(this, arguments);
    };
  }
})();
