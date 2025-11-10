;(function(){
  function load(){ try { if (typeof window.loadHistoryPage === 'function') return window.loadHistoryPage(); } catch(_){} }
  function refresh(){ return load(); }
  function init(){
    try {
      var prevBtn = document.getElementById('historyPrev');
      var nextBtn = document.getElementById('historyNext');
      var sizeSel = document.getElementById('historyPageSize');
      var csvBtn = document.getElementById('exportCsvBtn');
      var jsonBtn = document.getElementById('exportJsonBtn');

      if (prevBtn && !prevBtn._bound){
        prevBtn.addEventListener('click', function(){
          try {
            if (window.historyState && window.historyState.page > 1){ window.historyState.page--; }
          } catch(_){ }
          load();
        });
        prevBtn._bound = true;
      }
      if (nextBtn && !nextBtn._bound){
        nextBtn.addEventListener('click', function(){
          try {
            var hs = window.historyState || { page:1, pageSize:10, total:0 };
            var maxPage = Math.max(1, Math.ceil(Number(hs.total||0) / Number(hs.pageSize||10)));
            if (hs.page < maxPage){ hs.page++; }
          } catch(_){ }
          load();
        });
        nextBtn._bound = true;
      }
      if (sizeSel && !sizeSel._bound){
        sizeSel.addEventListener('change', function(e){
          try {
            var v = parseInt(e.target.value || '10', 10);
            if (!isNaN(v) && v > 0){ window.historyState.pageSize = v; window.historyState.page = 1; }
          } catch(_){ }
          load();
        });
        sizeSel._bound = true;
      }

      if (csvBtn && !csvBtn._bound){ csvBtn.addEventListener('click', function(){ window.location.href = '/api/decision_history/export?format=csv'; }); csvBtn._bound = true; }
      if (jsonBtn && !jsonBtn._bound){ jsonBtn.addEventListener('click', function(){ window.location.href = '/api/decision_history/export?format=json'; }); jsonBtn._bound = true; }
    } catch(e){ /* 忽略绑定错误 */ }
  }
  try { window.App = window.App || {}; window.App.history = { load: load, refresh: refresh, init: init }; } catch(_){ }
})();