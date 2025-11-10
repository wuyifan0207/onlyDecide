;(function(){
  function run(){ try { if (typeof window._runBacktest === 'function') return window._runBacktest(); } catch(_){} }
  function renderPage(){ try { if (typeof window.renderBacktestTradesPage === 'function') return window.renderBacktestTradesPage(); } catch(_){} }
  function init(){
    try {
      var runBtn = document.getElementById('runBtBtn');
      var prev = document.getElementById('btPrev');
      var next = document.getElementById('btNext');
      var sizeSel = document.getElementById('btPageSize');

      if (runBtn && !runBtn._bound){ runBtn.addEventListener('click', function(e){ e.preventDefault(); run(); }); runBtn._bound = true; }
      if (prev && !prev._bound){
        prev.addEventListener('click', function(){
          try { var st = window.backtestState || { page:1 }; if (st.page > 1) { st.page--; } } catch(_){ }
          renderPage();
        });
        prev._bound = true;
      }
      if (next && !next._bound){
        next.addEventListener('click', function(){
          try {
            var st = window.backtestState || { page:1, pageSize:20, total:0 };
            var maxPage = Math.max(1, Math.ceil(Number(st.total||0) / Number(st.pageSize||20)));
            if (st.page < maxPage){ st.page++; }
          } catch(_){ }
          renderPage();
        });
        next._bound = true;
      }
      if (sizeSel && !sizeSel._bound){
        sizeSel.addEventListener('change', function(e){
          try {
            var v = parseInt(e.target.value || '20', 10);
            if (!isNaN(v) && v > 0){ window.backtestState.pageSize = v; window.backtestState.page = 1; }
          } catch(_){ }
          renderPage();
        });
        sizeSel._bound = true;
      }
    } catch(e){ /* 忽略绑定错误 */ }
  }
  try { window.App = window.App || {}; window.App.bt = { run: run, renderPage: renderPage, init: init }; } catch(_){ }
})();