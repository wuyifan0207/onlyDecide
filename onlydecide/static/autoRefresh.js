;(function(){
  var timer = null;

  function getFreq(){
    var v = Number(document.body.getAttribute('data-ai-freq')) || 10;
    return Math.max(1, v);
  }

  function start(){
    try { if (timer) clearInterval(timer); } catch(_){}
    var freqNow = getFreq();
    timer = setInterval(function(){
      try {
        if (document.getElementById('autoRefresh')?.checked){
          if (typeof window.loadHistoryPage === 'function') window.loadHistoryPage();
          if (typeof window.loadLogs === 'function') window.loadLogs();
        }
      } catch(_){}
    }, freqNow * 1000);
    var label = document.getElementById('autoFreqLabel');
    if (label){ label.textContent = String(freqNow); }
  }

  function stop(){ if (timer){ try { clearInterval(timer); } catch(_){} timer = null; } }

  function bind(){
    try {
      var autoEl = document.getElementById('autoRefresh');
      if (autoEl && !autoEl._bound){
        autoEl.addEventListener('change', function(e){ if (e.target.checked) start(); else stop(); });
        autoEl._bound = true;
      }
      var freqInput = document.getElementById('autoFreqInput');
      if (freqInput && !freqInput._bound){
        freqInput.addEventListener('change', function(e){
          var v = Number(e.target.value||'');
          if (!isNaN(v) && v > 0){
            fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ ai_frequency: v }) })
              .then(function(){ return window.loadConfig ? window.loadConfig() : null; })
              .catch(function(){});
          }
        });
        freqInput._bound = true;
      }
    } catch(e){ /* 忽略 */ }
  }

  try {
    window.App = window.App || {};
    window.App.auto = { start: start, stop: stop, init: bind };
    // 兼容旧代码路径
    window.startAuto = start;
  } catch(_){}
})();