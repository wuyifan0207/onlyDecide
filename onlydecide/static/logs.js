;(function(){
  function load(){ try { if (typeof window.loadLogs === 'function') return window.loadLogs(); } catch(_){} }
  function init(){
    try {
      var btnAll = document.getElementById('clearLogsBtn');
      if (btnAll && !btnAll._bound){ btnAll.addEventListener('click', function(e){ e.preventDefault(); if (typeof window._clearLogs === 'function') window._clearLogs(); }); btnAll._bound = true; }
      var btnEcho = document.getElementById('clearEchoBtn');
      if (btnEcho && !btnEcho._bound){ btnEcho.addEventListener('click', function(e){ e.preventDefault(); if (typeof window._clearEcho === 'function') window._clearEcho(); }); btnEcho._bound = true; }
      var btnError = document.getElementById('clearErrorBtn');
      if (btnError && !btnError._bound){ btnError.addEventListener('click', function(e){ e.preventDefault(); if (typeof window._clearError === 'function') window._clearError(); }); btnError._bound = true; }
    } catch(_){ }
  }
  async function clear(){
    try {
      var ok = true;
      try { if (window.App && App.ui && typeof App.ui.confirm === 'function'){ ok = await App.ui.confirm('确定要清空最新日志（回显与错误）吗？', '请确认'); } } catch(_){ ok = true; }
      if (!ok) return;
      var res = await fetch('/api/logs/clear', { method: 'POST' });
      var ct = (res.headers && res.headers.get && res.headers.get('content-type')) || '';
      if (!res.ok || !String(ct).includes('application/json')){
        try { App.ui?.toast && App.ui.toast('清空失败: 非JSON响应或错误状态(' + (res.status||'?') + ')', 'error'); } catch(_){}
        return;
      }
      var data = await res.json();
      if (data && data.success){ try { App.ui?.toast && App.ui.toast('日志已清空', 'success'); } catch(_){}; await load(); }
      else { try { App.ui?.toast && App.ui.toast('清空失败: ' + (data?.error || '未知错误'), 'error'); } catch(_){} }
    } catch(e){ console.error(e); try { App.ui?.toast && App.ui.toast('清空失败: ' + e.message, 'error'); } catch(_){} }
  }
  async function clearEcho(){
    try {
      var ok = true;
      try { if (window.App && App.ui && typeof App.ui.confirm === 'function'){ ok = await App.ui.confirm('确定要清空“回显”日志吗？', '请确认'); } } catch(_){ ok = true; }
      if (!ok) return;
      var res = await fetch('/api/logs/clear_echo', { method: 'POST' });
      var ct = (res.headers && res.headers.get && res.headers.get('content-type')) || '';
      if (!res.ok || !String(ct).includes('application/json')){
        // 回退到统一接口
        try {
          res = await fetch('/api/logs/clear?type=echo', { method: 'POST' });
          ct = (res.headers && res.headers.get && res.headers.get('content-type')) || '';
        } catch(_){ }
      }
      if (!res.ok || !String(ct).includes('application/json')){ try { App.ui?.toast && App.ui.toast('清空失败: 非JSON响应(' + (res.status||'?') + ')', 'error'); } catch(_){}; return; }
      var data = await res.json();
      if (data && data.success){ try { App.ui?.toast && App.ui.toast('回显已清空', 'success'); } catch(_){}; await load(); }
      else { try { App.ui?.toast && App.ui.toast('清空失败: ' + (data?.error || '未知错误'), 'error'); } catch(_){} }
    } catch(e){ console.error(e); try { App.ui?.toast && App.ui.toast('清空失败: ' + e.message, 'error'); } catch(_){} }
  }
  async function clearError(){
    try {
      var ok = true;
      try { if (window.App && App.ui && typeof App.ui.confirm === 'function'){ ok = await App.ui.confirm('确定要清空“错误”日志吗？', '请确认'); } } catch(_){ ok = true; }
      if (!ok) return;
      var res = await fetch('/api/logs/clear_error', { method: 'POST' });
      var ct = (res.headers && res.headers.get && res.headers.get('content-type')) || '';
      if (!res.ok || !String(ct).includes('application/json')){
        // 回退到统一接口
        try {
          res = await fetch('/api/logs/clear?type=error', { method: 'POST' });
          ct = (res.headers && res.headers.get && res.headers.get('content-type')) || '';
        } catch(_){ }
      }
      if (!res.ok || !String(ct).includes('application/json')){ try { App.ui?.toast && App.ui.toast('清空失败: 非JSON响应(' + (res.status||'?') + ')', 'error'); } catch(_){}; return; }
      var data = await res.json();
      if (data && data.success){ try { App.ui?.toast && App.ui.toast('错误日志已清空', 'success'); } catch(_){}; await load(); }
      else { try { App.ui?.toast && App.ui.toast('清空失败: ' + (data?.error || '未知错误'), 'error'); } catch(_){} }
    } catch(e){ console.error(e); try { App.ui?.toast && App.ui.toast('清空失败: ' + e.message, 'error'); } catch(_){} }
  }
  try { window.App = window.App || {}; window.App.logs = { load: load, init: init }; } catch(_){ }
  try { window._clearLogs = clear; } catch(_){}
  try { window._clearEcho = clearEcho; } catch(_){}
  try { window._clearError = clearError; } catch(_){}
})();