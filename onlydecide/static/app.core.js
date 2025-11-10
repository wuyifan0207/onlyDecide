;(function(){
  try {
    if (!window.App){ window.App = {}; }
    // 轻量工具 + UI 弹窗/提示
    if (!App.util){ App.util = {}; }
    if (!App.ui){
      App.ui = {};
      // 动态创建样式弹窗与提示容器
      function ensureContainers(){
        try {
          var toast = document.getElementById('appToast');
          if (!toast){
            toast = document.createElement('div');
            toast.id = 'appToast';
            toast.className = 'toast-container';
            document.body.appendChild(toast);
          }
          var modal = document.getElementById('appModal');
          if (!modal){
            modal = document.createElement('div');
            modal.id = 'appModal';
            modal.className = 'modal';
            modal.innerHTML = '<div class="modal-content"><div class="modal-message" id="appModalMsg"></div><div class="modal-actions"><button class="btn" id="appModalOk">确定</button><button class="btn" id="appModalCancel">取消</button></div></div>';
            document.body.appendChild(modal);
          }
        } catch(e){ /* 忽略 */ }
      }

      // 样式提示（toast）
      App.ui.toast = function(message, type){
        try {
          ensureContainers();
          var cont = document.getElementById('appToast');
          var item = document.createElement('div');
          item.className = 'toast ' + (type ? ('toast-' + type) : 'toast-info');
          item.textContent = String(message||'');
          cont.appendChild(item);
          // 自动消失
          setTimeout(function(){ try { item.classList.add('fade-out'); } catch(_){} }, 2200);
          setTimeout(function(){ try { cont.removeChild(item); } catch(_){} }, 2800);
        } catch(e){ /* 忽略 */ }
      };

      // 样式确认/信息弹窗（返回 Promise）
      App.ui.confirm = function(message, title){
        return new Promise(function(resolve){
          try {
            ensureContainers();
            var modal = document.getElementById('appModal');
            var msg = document.getElementById('appModalMsg');
            var ok = document.getElementById('appModalOk');
            var cancel = document.getElementById('appModalCancel');
            msg.innerHTML = (title? ('<div style="font-weight:700;margin-bottom:6px;">'+String(title)+'</div>') : '') + String(message||'');
            modal.style.display = 'flex';
            // 绑定一次性事件
            function cleanup(){
              try { modal.style.display = 'none'; ok.onclick = null; cancel.onclick = null; } catch(_){}
            }
            ok.onclick = function(){ cleanup(); resolve(true); };
            cancel.style.display = '';
            cancel.onclick = function(){ cleanup(); resolve(false); };
          } catch(e){ resolve(false); }
        });
      };

      // 信息弹窗（只有确定）
      App.ui.alert = function(message, title){
        return new Promise(function(resolve){
          try {
            ensureContainers();
            var modal = document.getElementById('appModal');
            var msg = document.getElementById('appModalMsg');
            var ok = document.getElementById('appModalOk');
            var cancel = document.getElementById('appModalCancel');
            msg.innerHTML = (title? ('<div style="font-weight:700;margin-bottom:6px;">'+String(title)+'</div>') : '') + String(message||'');
            modal.style.display = 'flex';
            cancel.style.display = 'none';
            function cleanup(){ try { modal.style.display = 'none'; ok.onclick = null; } catch(_){} }
            ok.onclick = function(){ cleanup(); resolve(true); };
          } catch(e){ resolve(true); }
        });
      };
    }
  } catch(e){ /* 忽略 */ }
})();