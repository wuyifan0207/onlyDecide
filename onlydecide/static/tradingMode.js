;(function(){
  function updateButtons(mode){
    try {
      var simB = document.getElementById('simModeBtn');
      var liveB = document.getElementById('liveModeBtn');
      if (simB && liveB){
        try { simB.classList.remove('active'); liveB.classList.remove('active'); } catch(_){}
        if (mode === 'simulation') simB.classList.add('active'); else liveB.classList.add('active');
      }
    } catch(e){ /* 忽略 */ }
  }

  async function load(){
    try {
      var mode = 'simulation';
      try {
        var res = await fetch('/api/trading_mode');
        var data = await res.json();
        if (data && data.success && data.mode){ mode = data.mode; }
      } catch(_){}
      var el = document.getElementById('tradingMode'); if (el) el.textContent = mode;
      updateButtons(mode);
    } catch(e){ console.error(e); }
  }

  async function set(mode){
    try {
      if (!mode || (mode !== 'simulation' && mode !== 'live')){ try { App.ui?.toast && App.ui.toast('无效模式', 'error'); } catch(_){} return; }
      if (typeof window.showOverlay === 'function') window.showOverlay();
      var res = await fetch('/api/trading_mode', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: mode })
      });
      var data = await res.json();
      if (data && data.success){
        var el = document.getElementById('tradingMode'); if (el) el.textContent = data.mode || mode;
        var card = document.getElementById('tradingCard');
        if (card){
          try { card.classList.remove('mode-sim','mode-live'); } catch(_){}
          card.classList.add((data.mode||mode) === 'simulation' ? 'mode-sim' : 'mode-live');
          card.classList.add('mode-flash');
          setTimeout(function(){ try { card.classList.remove('mode-flash'); } catch(_){ } }, 620);
        }
        updateButtons(data.mode||mode);
        try { App.ui?.toast && App.ui.toast('交易模式已切换为: ' + (data.mode || mode), 'success'); } catch(_){}
      } else {
        try { App.ui?.toast && App.ui.toast('切换失败: ' + (data.error||'未知错误'), 'error'); } catch(_){}
      }
    } catch(e){ console.error(e); try { App.ui?.toast && App.ui.toast('切换失败: ' + e.message, 'error'); } catch(_){} }
    finally { if (typeof window.hideOverlay === 'function') window.hideOverlay(); }
  }

  function bind(){
    try {
      var simBtn = document.getElementById('simModeBtn');
      var liveBtn = document.getElementById('liveModeBtn');
      if (simBtn && !simBtn._bound){ simBtn.addEventListener('click', function(){ set('simulation'); }); simBtn._bound = true; }
      if (liveBtn && !liveBtn._bound){ liveBtn.addEventListener('click', function(){ set('live'); }); liveBtn._bound = true; }
    } catch(e){ /* 忽略 */ }
  }

  try {
    window.App = window.App || {};
    window.App.mode = { load: load, set: set, init: bind };
  } catch(_){}
})();