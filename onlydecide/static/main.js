;(function(){
  'use strict';

  function fmtNum(n, d){
    if (d === undefined) d = 2;
    if (n === null || n === undefined || isNaN(n)) return '--';
    try { return Number(n).toFixed(d); } catch(e){ return String(n); }
  }

  var overlayEl = document.getElementById('loadingOverlay');
  function showOverlay(){ if (overlayEl) overlayEl.style.display = 'flex'; }
  function hideOverlay(){ if (overlayEl) overlayEl.style.display = 'none'; }
  function setBtnLoading(btn, text){
    if (!btn) return;
    btn.dataset.originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = text;
  }
  function clearBtnLoading(btn){
    if (!btn) return;
    btn.disabled = false;
    if (btn.dataset.originalText) btn.textContent = btn.dataset.originalText;
  }

  function drawEquityCurve(curve){
    try {
      var cvs = document.getElementById('btEquity');
      if (!cvs) return;
      var dpr = window.devicePixelRatio || 1;
      var cssW = cvs.clientWidth || 600;
      var cssH = cvs.clientHeight || 160;
      cvs.width = Math.max(300, Math.floor(cssW * dpr));
      cvs.height = Math.max(120, Math.floor(cssH * dpr));
      var ctx = cvs.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssW, cssH);
      ctx.fillStyle = 'rgba(255,255,255,0.03)';
      ctx.fillRect(0, 0, cssW, cssH);

      if (!curve || curve.length < 2){
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.font = '12px system-ui';
        ctx.fillText('\u8d44\u91d1\u66f2\u7ebf: \u6570\u636e\u4e0d\u8db3', 10, 20);
        return;
      }
      var vals = curve.map(function(p){ return Number(p.equity)||0; });
      var minV = Math.min.apply(null, vals);
      var maxV = Math.max.apply(null, vals);
      if (maxV === minV){ maxV = minV + 1; }
      var padX = 12, padY = 8;
      var W = cssW - padX*2;
      var H = cssH - padY*2;
      var accent = getComputedStyle(document.documentElement).getPropertyValue('--accent') || '#5be7a9';
      var ctx2 = cvs.getContext('2d');
      ctx2.strokeStyle = accent;
      ctx2.lineWidth = 1.2;
      ctx2.beginPath();
      for (var i=0;i<vals.length;i++){
        var x = padX + (W * i / (vals.length - 1));
        var y = padY + (H * (1 - (vals[i] - minV) / (maxV - minV)));
        if (i === 0) ctx2.moveTo(x, y); else ctx2.lineTo(x, y);
      }
      ctx2.stroke();
    } catch(e){ console.error(e); }
  }

  // 绘制滚动胜率趋势折线
  function drawWinRateTrend(values){
    try {
      var cvs = document.getElementById('btWinTrend');
      if (!cvs || !values || values.length < 2) return;
      var dpr = window.devicePixelRatio || 1;
      var cssW = cvs.clientWidth || 600;
      var cssH = cvs.clientHeight || 60;
      cvs.width = Math.max(300, Math.floor(cssW * dpr));
      cvs.height = Math.max(60, Math.floor(cssH * dpr));
      var ctx = cvs.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssW, cssH);
      ctx.fillStyle = 'rgba(255,255,255,0.03)';
      ctx.fillRect(0, 0, cssW, cssH);
      var padX = 6, padY = 6;
      var W = cssW - padX*2;
      var H = cssH - padY*2;
      var accent = getComputedStyle(document.documentElement).getPropertyValue('--accent') || '#5be7a9';
      var ctx2 = cvs.getContext('2d');
      ctx2.strokeStyle = accent;
      ctx2.lineWidth = 1.2;
      ctx2.beginPath();
      for (var i=0;i<values.length;i++){
        var x = padX + (W * i / (values.length - 1));
        var y = padY + (H * (1 - Math.max(0, Math.min(100, values[i])) / 100));
        if (i === 0) ctx2.moveTo(x, y); else ctx2.lineTo(x, y);
      }
      ctx2.stroke();
    } catch(e){ console.error(e); }
  }

  var historyState = {
    page: 1,
    pageSize: 10,
    total: 0,
    lastLatestKey: null,
    symbol: (document.body.getAttribute('data-symbol') || '')
  };
  // 暴露历史状态，便于模块访问
  try { window.historyState = historyState; } catch(_){}
  // Backtest pagination state
  var backtestState = {
    page: 1,
    pageSize: 20,
    total: 0,
    trades: []
  };
  // 暴露回测状态，便于模块访问
  try { window.backtestState = backtestState; } catch(_){}

  async function loadHistoryPage(){
    try {
      var url = '/api/decision_history?page=' + historyState.page + '&page_size=' + historyState.pageSize + '&symbol=' + encodeURIComponent(historyState.symbol||'');
      var res = await fetch(url);
      var data = await res.json();
      var list = (data && data.data) || [];
      historyState.total = Number((data && data.total) || 0);
      var tbody = document.getElementById('historyTbody');
      var info = document.getElementById('historyPageInfo');
      var maxPage = Math.max(1, Math.ceil(historyState.total / historyState.pageSize));
      if (historyState.page > maxPage) historyState.page = maxPage;
      if (info){ info.textContent = '\u7b2c ' + String(historyState.page) + ' / ' + String(maxPage) + ' \u9875\uff08\u5171 ' + String(historyState.total) + ' \u6761\uff09'; }
      if (tbody){
        if (!list.length){ tbody.innerHTML = '<tr><td colspan="7" class="muted">(\u6682\u65e0\u6570\u636e)</td></tr>'; }
        else {
          var html = list.map(function(it){
            var tp = fmtNum(it.take_profit_price, 2);
            var sl = fmtNum(it.stop_loss_price, 2);
            var pxRaw = Number(it.current_price || 0);
            var px = fmtNum(pxRaw, 2);
            var szUsdt = fmtNum(Number(it.position_size||0) * (pxRaw>0?pxRaw:0), 2);
            var executed = it.executed ? '是' : '否';
            // 格式化时间，只显示到秒
            var timestamp = it.timestamp || '';
            if (timestamp && timestamp.length > 19) {
              timestamp = timestamp.substring(0, 19); // 只保留到秒
            }
            return '<tr>'+
              '<td>'+ timestamp +'</td>'+
              '<td>'+ (it.action||'--') +'</td>'+
              '<td>'+ (it.confidence_level||'--') +'</td>'+
              '<td>'+ szUsdt + ' USDT</td>'+ 
              '<td>'+ tp + ' / ' + sl +'</td>'+
              '<td>'+ px +'</td>'+
              '<td>'+ executed +'</td>'+
            '</tr>';
          }).join('');
          tbody.innerHTML = html;
        }
      }

      var latest = list && list[0];
      if (latest){
        var status = document.getElementById('aiStatus');
        document.getElementById('aiAction').textContent = latest.action || '--';
        document.getElementById('aiConf').textContent = latest.confidence_level || '--';
        document.getElementById('aiReason').textContent = latest.reason || '--';
        var curPx = Number(latest.current_price || 0);
        var szUsdt = fmtNum(Number(latest.position_size||0) * (curPx>0?curPx:0), 2);
        document.getElementById('aiSize').textContent = szUsdt + ' USDT';
        document.getElementById('aiTPSL').textContent = 'TP: ' + fmtNum(latest.take_profit_price, 2) + ' / SL: ' + fmtNum(latest.stop_loss_price, 2);
        if (status) status.innerHTML = '<span class="ok">\u81ea\u52a8\u66f4\u65b0\u6700\u65b0AI\u51b3\u7b56</span>';
      }

      var key = latest ? String(latest.timestamp || '') + '|' + String(latest.action || '') + '|' + String(latest.reason || '') : null;
      if (key && key !== historyState.lastLatestKey){
        historyState.lastLatestKey = key;
        if (historyState.page === 1){
          var wrap = document.getElementById('historyWrap');
          if (wrap) wrap.scrollTop = 0;
        }
      }
    } catch (e) { console.error(e); }
  }
  // 暴露历史加载函数
  try { window.loadHistoryPage = loadHistoryPage; } catch(_){}

  async function loadLogs(){
    try {
      var res = await fetch('/api/logs');
      var data = await res.json();
      document.getElementById('echoLog').textContent = (data.echo || []).join('\n') || '(\u6682\u65e0)';
      document.getElementById('errorLog').textContent = (data.error || []).join('\n') || '(\u6682\u65e0)';
    } catch (e) { console.error(e); }
  }
  // 暴露日志加载函数
  try { window.loadLogs = loadLogs; } catch(_){}

  // 获取当前交易对（通过备用接口 /api/trading_config2）
  async function loadSymbol(){
    try {
      let sym = null;
      // 优先从备用接口获取
      try {
        var res = await fetch('/api/trading_config2');
        var data = await res.json();
        if (data && data.success && data.config && data.config.symbol){
          sym = data.config.symbol;
        }
      } catch(_){}
      // 回退到 /api/config
      if (!sym){
        try {
          var res2 = await fetch('/api/config');
          var data2 = await res2.json();
          if (data2 && data2.success && data2.config && data2.config.symbol){
            sym = data2.config.symbol;
          }
        } catch(_){}
      }
      // 最终回退默认
      sym = sym || 'ETH-USDT-SWAP';
      historyState.symbol = sym;
      document.body.setAttribute('data-symbol', sym);
      var curEl = document.getElementById('currentSymbol'); if (curEl) curEl.textContent = sym;
      var sel = document.getElementById('symbolSelect'); if (sel) sel.value = sym;
      var sel2 = document.getElementById('symbolSelect2'); if (sel2) sel2.value = sym;
    } catch(e){ console.error(e); }
  }

  // 获取当前交易对（统一使用 /api/symbol GET）
  async function loadSymbol2(){
    try {
      var sym = null;
      try {
        var res = await fetch('/api/symbol');
        var data = await res.json();
        if (data && data.success && data.symbol){ sym = data.symbol; }
      } catch(_){ }
      sym = sym || (document.body.getAttribute('data-symbol') || 'ETH-USDT-SWAP');
      historyState.symbol = sym;
      document.body.setAttribute('data-symbol', sym);
      var curEl = document.getElementById('currentSymbol'); if (curEl) curEl.textContent = sym;
      var sel = document.getElementById('symbolSelect'); if (sel) sel.value = sym;
    } catch(e){ console.error(e); }
  }

  // ========== 交易模式（仅展示用途） ==========
  async function loadTradingMode2(){
    try {
      var mode = 'simulation';
      try {
        var res = await fetch('/api/trading_mode');
        var data = await res.json();
        if (data && data.success && data.mode){ mode = data.mode; }
      } catch(_){}
      var el = document.getElementById('tradingMode'); if (el) el.textContent = mode;
      // 设置按钮激活态（浅绿色背景）
      var simB = document.getElementById('simModeBtn');
      var liveB = document.getElementById('liveModeBtn');
      if (simB && liveB){
        try { simB.classList.remove('active'); liveB.classList.remove('active'); } catch(_){}
        if (mode === 'simulation') simB.classList.add('active'); else liveB.classList.add('active');
      }
    } catch(e){ console.error(e); }
  }

  async function setTradingMode2(mode){
    try {
      if (!mode || (mode !== 'simulation' && mode !== 'live')){ try { App.ui?.toast && App.ui.toast('无效模式', 'error'); } catch(_){} return; }
      showOverlay();
      var res = await fetch('/api/trading_mode', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: mode })
      });
      var data = await res.json();
      if (data && data.success){
        var el = document.getElementById('tradingMode'); if (el) el.textContent = data.mode || mode;
        // 模式切换动画与高亮
        var card = document.getElementById('tradingCard');
        if (card){
          try { card.classList.remove('mode-sim','mode-live'); } catch(_){}
          card.classList.add((data.mode||mode) === 'simulation' ? 'mode-sim' : 'mode-live');
          card.classList.add('mode-flash');
          setTimeout(function(){ try { card.classList.remove('mode-flash'); } catch(_){ } }, 620);
        }
        // 设置按钮激活态（浅绿色背景）
        var simB = document.getElementById('simModeBtn');
        var liveB = document.getElementById('liveModeBtn');
        if (simB && liveB){
          try { simB.classList.remove('active'); liveB.classList.remove('active'); } catch(_){}
          if ((data.mode||mode) === 'simulation') simB.classList.add('active'); else liveB.classList.add('active');
        }
        try { App.ui?.toast && App.ui.toast('交易模式已切换为: ' + (data.mode || mode), 'success'); } catch(_){}
      } else {
        try { App.ui?.toast && App.ui.toast('切换失败: ' + (data.error||'未知错误'), 'error'); } catch(_){}
      }
    } catch(e){ console.error(e); try { App.ui?.toast && App.ui.toast('切换失败: ' + e.message, 'error'); } catch(_){} }
    finally { hideOverlay(); }
  }

  // ========== 主题切换 ==========
  function applyTheme(theme){
    try {
      var body = document.body;
      var classes = Array.from(body.classList || []);
      classes.forEach(function(c){ if (String(c||'').indexOf('theme-') === 0) { body.classList.remove(c); } });
      var cls = 'theme-' + (theme || 'dark');
      body.classList.add(cls);
      try { localStorage.setItem('dashboard_theme', String(theme||'dark')); } catch(_){}
    } catch(e){ console.error(e); }
  }

  function initThemeSwitcher(){
    try {
      var sel = document.getElementById('themeSel');
      var saved = null; try { saved = localStorage.getItem('dashboard_theme'); } catch(_){}
      var v = saved || 'dark';
      applyTheme(v);
      if (sel){
        sel.value = v;
        sel.addEventListener('change', function(e){
          try { document.body.classList.add('theme-animate'); } catch(_){}
          applyTheme(String(e.target.value||'dark'));
          setTimeout(function(){ try { document.body.classList.remove('theme-animate'); } catch(_){} }, 350);
        });
      }
    } catch(e){ console.error(e); }
  }

  // 设置交易对（使用稳定接口 /api/symbol）
  async function setSymbol(sym){
    try {
      showOverlay();
      var res = await fetch('/api/symbol', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym })
      });
      var data = await res.json();
      if (data.success){
        var cur = data.symbol || sym;
        historyState.symbol = cur;
        document.body.setAttribute('data-symbol', cur);
        var curEl = document.getElementById('currentSymbol'); if (curEl) curEl.textContent = cur;
        await loadHistoryPage();
        try { App.ui?.toast && App.ui.toast('交易对已切换为: ' + cur, 'success'); } catch(_){}
      } else {
        try { App.ui?.toast && App.ui.toast('切换失败: ' + (data.error||'未知错误'), 'error'); } catch(_){}
      }
    } catch(e){ console.error(e); try { App.ui?.toast && App.ui.toast('切换失败: ' + e.message, 'error'); } catch(_){} }
    finally { hideOverlay(); }
  }

  // 从后端拉取可用交易对并填充下拉框
  async function loadAvailableSymbols(){
    try {
      var res = await fetch('/api/available_symbols');
      var data = await res.json();
      var list = (data && data.symbols) || [];
      var sel1 = document.getElementById('symbolSelect');
      var sel2 = document.getElementById('symbolSelect2');
      [sel1, sel2].forEach(function(sel){
        if (sel){
          var html = list.map(function(s){ return '<option value="'+s+'">'+s+'</option>'; }).join('');
          sel.innerHTML = html;
          var cur = document.body.getAttribute('data-symbol') || '';
          if (cur) sel.value = cur;
        }
      });
    } catch(e){ console.error(e); }
  }

  async function loadAI(){
    try {
      var res = await fetch('/api/ai_decision');
      var data = await res.json();
      if (!data.success) return;
      var d = data.decision || {};
      var curPx = Number(data.current_price || 0);
      document.getElementById('aiAction').textContent = d.action || '--';
      document.getElementById('aiConf').textContent = d.confidence_level || '--';
      document.getElementById('aiReason').textContent = d.reason || '--';
      var szUsdt = fmtNum(Number(d.position_size||0) * (curPx>0?curPx:0), 2);
      document.getElementById('aiSize').textContent = szUsdt + ' USDT';
      document.getElementById('aiTPSL').textContent = 'TP: ' + fmtNum(d.take_profit_price, 2) + ' / SL: ' + fmtNum(d.stop_loss_price, 2);
      var status = document.getElementById('aiStatus');
      if (status) status.innerHTML = '<span class="ok">AI\u51b3\u7b56\u751f\u6210\u5b8c\u6210</span>';
    } catch (e) { console.error(e); }
  }

  // ==================== 新功能模块 ====================

  // 清除历史数据
  async function clearHistory(){
    try {
      var ok = true;
      try {
        if (App.ui && typeof App.ui.confirm === 'function'){
          ok = await App.ui.confirm('确定要清除所有历史决策数据吗？此操作不可撤销！', '请确认');
        }
      } catch(_){ ok = true; }
      if (!ok) return;
      
      showOverlay();
      var res = await fetch('/api/decision_history/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      var data = await res.json();
      
      if (data.success) {
        try { App.ui?.toast && App.ui.toast('已清除 ' + data.deleted_count + ' 条历史决策记录', 'success'); } catch(_){}
        await loadHistoryPage(); // 重新加载历史记录
      } else {
        try { App.ui?.toast && App.ui.toast('清除失败: ' + (data.error || '未知错误'), 'error'); } catch(_){}
      }
    } catch (e) { 
      console.error(e);
      try { App.ui?.toast && App.ui.toast('清除失败: ' + e.message, 'error'); } catch(_){}
    } finally {
      hideOverlay();
    }
  }


  // 发送通知
  async function sendNotification(title, message, level){
    try {
      var res = await fetch('/api/notifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title, message: message, level: level || 'info' })
      });
      var data = await res.json();
      return data.success;
    } catch (e) { 
      console.error(e);
      return false;
    }
  }


  window._refreshClick = async function(){
    var refreshBtn = document.getElementById('refreshBtn');
    try {
      setBtnLoading(refreshBtn, '\u5237\u65b0\u4e2d...');
      showOverlay();
      await Promise.all([loadHistoryPage(), loadLogs()]);
    } finally {
      clearBtnLoading(refreshBtn);
      hideOverlay();
    }
  };

  window._aiClick = async function(){
    var aiBtn = document.getElementById('aiBtn');
    var allowManual = document.getElementById('allowManualAI');
    try {
      if (allowManual && !allowManual.checked){
        var status = document.getElementById('aiStatus');
        if (status) status.innerHTML = '<span class="muted">\u624b\u52a8AI\u751f\u6210\u5df2\u7981\u7528</span>';
        return;
      }
      setBtnLoading(aiBtn, '\u751f\u6210\u4e2d...');
      showOverlay();
      await loadAI();
    } finally {
      clearBtnLoading(aiBtn);
      hideOverlay();
    }
  };

  window._runBacktest = async function(){
    var btn = document.getElementById('runBtBtn');
    try {
      setBtnLoading(btn, '\u56de\u6d4b\u4e2d...');
      showOverlay();
      var eq = parseFloat(document.getElementById('btInitial') ? document.getElementById('btInitial').value : '10000');
      if (isNaN(eq)) eq = 10000;
      var url = '/api/backtest?symbol=' + encodeURIComponent(historyState.symbol||'') + '&initial_equity=' + String(eq);
      var szEl = document.getElementById('btPosSize');
      var levEl = document.getElementById('btLeverage');
      var sz = szEl ? parseFloat(szEl.value) : NaN;
      var lev = levEl ? parseFloat(levEl.value) : NaN;
      if (!isNaN(sz) && sz > 0) { url += '&position_size=' + String(sz); }
      if (!isNaN(lev) && lev > 0) { url += '&leverage=' + String(lev); }
      var res = await fetch(url);
      var data = await res.json();
      if (!data.success){ throw new Error(data.error || '回测失败'); }
      var m = data.metrics || {}; var trades = data.trades || [];
      var summaryEl = document.getElementById('btSummary');
      if (summaryEl){
        var extra = [];
        if (m.position_size_override !== undefined && m.position_size_override !== null) { extra.push('\u81ea\u5b9a\u4e49\u4ed3\u4f4d: ' + fmtNum(m.position_size_override,2) + ' USDT'); }
        if (m.leverage_used !== undefined && m.leverage_used !== null) { extra.push('\u6760\u6746: ' + String(m.leverage_used) + 'x'); }
        var line = '\u8d77\u59cb\u8d44\u91d1: ' + fmtNum(m.starting_equity,2) + ' USDT；\u7ed3\u675f\u8d44\u91d1: ' + fmtNum(m.ending_equity,2) + ' USDT；\u603b\u76c8\u4e8f: ' + fmtNum(m.total_pnl,2) + ' USDT；\u4ea4\u6613\u6570: ' + String(m.num_trades||0) + '；\u80dc\u7387: ' + fmtNum(((m.win_rate||0)*100),2) + '%；\u6700\u5927\u56de\u64a4: ' + fmtNum(((m.max_drawdown||0)*100),2) + '%；' + (extra.join('；')||'');
        summaryEl.innerHTML = line;
      }
      var panel = document.getElementById('btStatsPanel');
      if (panel){
        var total = trades.length;
        var wins = 0, longs = 0, shorts = 0;
        for (var i=0;i<trades.length;i++){
          var t = trades[i] || {};
          if ((t.pnl_usdt||0) >= 0) wins++;
          if (String(t.side||'').indexOf('long') >= 0) longs++; else if (String(t.side||'').indexOf('short') >= 0) shorts++;
        }
        var el;
        el = document.getElementById('btStatTotal'); if (el) el.textContent = String(total||0);
        el = document.getElementById('btStatWins'); if (el) el.textContent = String(wins||0);
        el = document.getElementById('btStatLosses'); if (el) el.textContent = String(Math.max(0, total - wins));
        el = document.getElementById('btStatLongs'); if (el) el.textContent = String(longs||0);
        el = document.getElementById('btStatShorts'); if (el) el.textContent = String(shorts||0);
        // extra stats: win rate, max drawdown, average return%
        var winRateEl = document.getElementById('btStatWinRate');
        var ddEl = document.getElementById('btStatDD');
        var avgREl = document.getElementById('btStatAvgR');
        var sumReturnPct = 0;
        for (var j=0;j<trades.length;j++) { sumReturnPct += Number(trades[j].return_pct || 0); }
        if (winRateEl) winRateEl.textContent = fmtNum(total>0 ? (wins/total*100) : ((m.win_rate||0)*100), 2) + '%';
        if (ddEl) ddEl.textContent = fmtNum(((m.max_drawdown||0)*100), 2) + '%';
        if (avgREl) avgREl.textContent = fmtNum(total>0 ? (sumReturnPct/total*100) : 0, 2) + '%';

        // extra metrics: P/L ratio and streaks
        var profitSum = 0, profitCount = 0;
        var lossSumAbs = 0, lossCount = 0;
        var maxWinStreak = 0, maxLoseStreak = 0;
        var curWinStreak = 0, curLoseStreak = 0;
        var pnlArr = [];
        for (var k=0;k<trades.length;k++){
          var tt = trades[k] || {};
          var pnl = (tt.pnl_usdt!=null ? tt.pnl_usdt : tt.pnl) || 0;
          pnlArr.push(pnl);
          if (pnl >= 0){
            profitSum += pnl; profitCount++;
            curWinStreak++; curLoseStreak = 0;
            if (curWinStreak > maxWinStreak) maxWinStreak = curWinStreak;
          } else {
            lossSumAbs += Math.abs(pnl); lossCount++;
            curLoseStreak++; curWinStreak = 0;
            if (curLoseStreak > maxLoseStreak) maxLoseStreak = curLoseStreak;
          }
        }
        var plEl = document.getElementById('btStatPLRatio');
        var maxLoseEl = document.getElementById('btStatMaxLoseStreak');
        var maxWinEl = document.getElementById('btStatMaxWinStreak');
        var plRatio = (profitCount>0 && lossCount>0) ? (profitSum/profitCount) / (lossSumAbs/lossCount) : null;
        if (plEl) plEl.textContent = (plRatio==null ? '--' : fmtNum(plRatio,2));
        if (maxLoseEl) maxLoseEl.textContent = String(maxLoseStreak||0);
        if (maxWinEl) maxWinEl.textContent = String(maxWinStreak||0);

        // win-rate rolling trend (window=10)
        var windowSize = 10;
        var trend = [];
        if (pnlArr.length >= windowSize){
          for (var w=windowSize; w<=pnlArr.length; w++){
            var winsInWindow = 0;
            for (var u=w-windowSize; u<w; u++){ if ((pnlArr[u]||0) >= 0) winsInWindow++; }
            trend.push(100*winsInWindow/windowSize);
          }
        }
        drawWinRateTrend(trend);
        
        // 查找最大盈利和最大亏损单子
        var maxProfitTrade = null;
        var maxLossTrade = null;
        for (var t=0; t<trades.length; t++){
          var trade = trades[t];
          var pnl = (trade.pnl_usdt!=null ? trade.pnl_usdt : trade.pnl) || 0;
          
          if (pnl > 0 && (!maxProfitTrade || pnl > (maxProfitTrade.pnl_usdt||maxProfitTrade.pnl||0))){
            maxProfitTrade = trade;
          }
          if (pnl < 0 && (!maxLossTrade || pnl < (maxLossTrade.pnl_usdt||maxLossTrade.pnl||0))){
            maxLossTrade = trade;
          }
        }
        
        // 格式化时间，只显示到秒
        function formatTimeToSeconds(timestamp) {
          if (!timestamp) return '';
          if (timestamp.length > 19) {
            return timestamp.substring(0, 19); // 只保留到秒
          }
          return timestamp;
        }
        
        // 显示最大盈利单
        var maxProfitEl = document.getElementById('btMaxProfitTrade');
        if (maxProfitEl) {
          if (maxProfitTrade) {
            var enterTime = formatTimeToSeconds(maxProfitTrade.enter_time);
            var exitTime = formatTimeToSeconds(maxProfitTrade.exit_time);
            maxProfitEl.innerHTML = 
              '方向: ' + (maxProfitTrade.side||'--') + '<br>' +
              '入场: ' + enterTime + '<br>' +
              '出场: ' + exitTime + '<br>' +
              '盈亏: ' + fmtNum((maxProfitTrade.pnl_usdt||maxProfitTrade.pnl||0),2) + ' USDT<br>' +
              '收益: ' + fmtNum(((maxProfitTrade.return_pct||0)*100),2) + '%';
          } else {
            maxProfitEl.textContent = '暂无盈利单';
          }
        }
        
        // 显示最大亏损单
        var maxLossEl = document.getElementById('btMaxLossTrade');
        if (maxLossEl) {
          if (maxLossTrade) {
            var enterTime = formatTimeToSeconds(maxLossTrade.enter_time);
            var exitTime = formatTimeToSeconds(maxLossTrade.exit_time);
            maxLossEl.innerHTML = 
              '方向: ' + (maxLossTrade.side||'--') + '<br>' +
              '入场: ' + enterTime + '<br>' +
              '出场: ' + exitTime + '<br>' +
              '盈亏: ' + fmtNum((maxLossTrade.pnl_usdt||maxLossTrade.pnl||0),2) + ' USDT<br>' +
              '收益: ' + fmtNum(((maxLossTrade.return_pct||0)*100),2) + '%';
          } else {
            maxLossEl.textContent = '暂无亏损单';
          }
        }
      }
      // save trades and render paginated table
      backtestState.trades = trades.slice();
      backtestState.total = backtestState.trades.length;
      backtestState.page = 1;
      var btSizeSel = document.getElementById('btPageSize');
      if (btSizeSel){ var v = parseInt(btSizeSel.value || '20', 10); backtestState.pageSize = isNaN(v) ? 20 : v; }
      renderBacktestTradesPage();
      // 使用后端返回的字段名 `curve` 绘制资金曲线
      drawEquityCurve(data.curve || []);
    } catch(e){
      console.error(e);
      try { if (window.App && App.ui && typeof App.ui.toast === 'function') App.ui.toast('回测失败: ' + e.message, 'error'); } catch(_){ }
    } finally {
      clearBtnLoading(btn);
      hideOverlay();
    }
  };

  function renderBacktestTradesPage(){
    var tbody = document.getElementById('btTradesTbody');
    var info = document.getElementById('btPageInfo');
    if (!tbody) return;
    var total = backtestState.total;
    var pageSize = backtestState.pageSize || 20;
    var maxPage = Math.max(1, Math.ceil(total / pageSize));
    if (backtestState.page > maxPage) backtestState.page = maxPage;
    if (info){ info.textContent = '\u7b2c ' + String(backtestState.page) + ' / ' + String(maxPage) + ' \u9875\uff08\u5171 ' + String(total) + ' \u6761\uff09'; }
    if (!total){ tbody.innerHTML = '<tr><td colspan="8" class="muted">(无交易)</td></tr>'; return; }
    var start = (backtestState.page - 1) * pageSize;
    var end = Math.min(total, start + pageSize);
      // 统一到秒的时间显示
      function fmtSec(ts){ if (!ts) return ''; return (String(ts).length > 19) ? String(ts).substring(0,19) : String(ts); }
      var html = backtestState.trades.slice(start, end).map(function(t){
      var size = (t.position_size!=null ? t.position_size : t.size);
      var sizeUsdt = fmtNum(Number(size||0) * (Number(t.entry_price||0)), 2);
      var pnl = (t.pnl_usdt!=null ? t.pnl_usdt : t.pnl);
      return '<tr>'+
        '<td>'+ fmtSec(t.enter_time) +'</td>'+
        '<td>'+ fmtSec(t.exit_time) +'</td>'+
        '<td>'+ (t.side||'') +'</td>'+
        '<td>'+ fmtNum(t.entry_price,2) +'</td>'+
        '<td>'+ fmtNum(t.exit_price,2) +'</td>'+
        '<td>'+ sizeUsdt + ' USDT</td>'+
        '<td>'+ fmtNum(pnl,2) +'</td>'+
        '<td>'+ fmtNum(((t.return_pct||0)*100),2) +'%</td>'+
      '</tr>';
    }).join('');
    tbody.innerHTML = html;
  }
  // 暴露回测渲染函数
  try { window.renderBacktestTradesPage = renderBacktestTradesPage; } catch(_){}

  // 初始化页面
  async function initPage(){
    await loadConfig();
    await loadAvailableSymbols();
    await loadSymbol2();
    try { if (window.App && App.mode && typeof App.mode.load === 'function') { await App.mode.load(); } else { await loadTradingMode2(); } } catch(_){}
    await loadHistoryPage();
    await loadLogs();
    // 设置自动刷新（优先使用模块实现）
    try { if (window.App && App.auto && typeof App.auto.init === 'function') App.auto.init(); } catch(_){}
    try { if (window.App && App.auto && typeof App.auto.start === 'function') App.auto.start(); else if (typeof window.startAuto === 'function') window.startAuto(); else startAuto(); } catch(_){}
  }

  // 统一入口：按固定顺序启动页面各模块（优先模块接口，保留回退）
  try {
    window.App = window.App || {};
    window.App.bootstrap = async function(){
      await loadConfig();
      await loadAvailableSymbols();
      await loadSymbol2();
      if (window.App?.mode?.load) { await App.mode.load(); } else { await loadTradingMode2(); }
      if (window.App?.history?.load) { await App.history.load(); } else { await loadHistoryPage(); }
      if (window.App?.history?.init) { App.history.init(); }
      if (window.App?.logs?.load) { await App.logs.load(); } else { await loadLogs(); }
      if (window.App?.logs?.init) { App.logs.init(); }
      if (window.App?.bt?.init) { App.bt.init(); }
      if (window.App?.auto?.init) { App.auto.init(); }
      if (window.App?.auto?.start) { App.auto.start(); } else if (typeof window.startAuto === 'function') { window.startAuto(); } else { startAuto(); }
    };
  } catch(_){}

  // 导出到全局
  window._refreshClick = function(){
    loadHistoryPage();
    loadLogs();
  };
  window._aiClick = function(){
    if (!document.getElementById('allowManualAI')?.checked){
      try { if (window.App && App.ui && typeof App.ui.toast === 'function') App.ui.toast('请先勾选"允许手动生成AI"', 'info'); } catch(_){}
      return;
    }
    var btn = document.getElementById('aiBtn');
    var status = document.getElementById('aiStatus');
    var cardLoading = document.getElementById('aiCardLoading');
    setBtnLoading(btn, '生成中...');
    if (cardLoading) cardLoading.style.display = 'flex';
    if (status) status.textContent = '生成中...';
    loadAI().then(function(){
      if (status) status.textContent = '已生成，AI卡片数据已更新';
      return loadHistoryPage();
    }).catch(function(e){
      console.error(e);
      if (status) status.innerHTML = '<span class="bad">生成失败：' + (e && e.message ? e.message : '未知错误') + '</span>';
      try { if (window.App && App.ui && typeof App.ui.toast === 'function') App.ui.toast('生成失败: ' + (e && e.message ? e.message : '未知错误'), 'error'); } catch(_){}
    }).finally(function(){
      clearBtnLoading(btn);
      if (cardLoading) cardLoading.style.display = 'none';
    });
  };
  window._clearHistory = clearHistory;

  document.addEventListener('DOMContentLoaded', function(){
    var refreshBtn = document.getElementById('refreshBtn');
    var aiBtn = document.getElementById('aiBtn');
    if (refreshBtn && !refreshBtn._bound) { refreshBtn.addEventListener('click', function(e){ e.preventDefault(); window._refreshClick(); }); refreshBtn._bound = true; }
    if (aiBtn && !aiBtn._bound) { aiBtn.addEventListener('click', function(e){ e.preventDefault(); window._aiClick(); }); aiBtn._bound = true; }

    // 回测控件绑定迁移至模块 App.bt.init()

    var timer = null;
    function startAuto(){
      if (timer) clearInterval(timer);
      var freqNow = Number(document.body.getAttribute('data-ai-freq')) || 10;
      timer = setInterval(function(){
        if (document.getElementById('autoRefresh')?.checked){
          loadHistoryPage();
          loadLogs();
        }
      }, Math.max(1, freqNow) * 1000);
      var label = document.getElementById('autoFreqLabel');
      if (label){ label.textContent = String(freqNow); }
    }
    // 使自动轮询函数可在闭包外使用（供 loadConfig 调用）
    try { window.startAuto = startAuto; } catch(_){}
    function stopAuto(){ if (timer) { clearInterval(timer); timer = null; } }
    var autoEl = document.getElementById('autoRefresh');
    if (autoEl) { autoEl.addEventListener('change', function(e){ if (e.target.checked) startAuto(); else stopAuto(); }); }
    // 统一暴露到命名空间，减少全局散乱引用（不覆盖已有模块实现）
    try {
      window.App = window.App || {};
      window.App.auto = window.App.auto || { start: startAuto, stop: stopAuto };
    } catch(_){}

    // 历史分页控件绑定迁移至模块 App.history.init()

    // 历史导出按钮绑定迁移至模块 App.history.init()

    // 绑定交易对选择
    var symbolSel2 = document.getElementById('symbolSelect2');
    if (symbolSel2 && !symbolSel2._bound){
      symbolSel2.addEventListener('change', function(e){ var v = String(e.target.value||''); if (v) setSymbol(v); });
      symbolSel2._bound = true;
    }

    // 绑定仓位与杠杆设置
    var orderLev = document.getElementById('orderLeverage');
    var orderPos = document.getElementById('orderPosSize');
    var orderPosEnable = document.getElementById('orderPosEnable');
    if (orderLev && !orderLev._bound){
      orderLev.addEventListener('change', function(e){
        var v = Number(e.target.value||'');
        if (!isNaN(v) && v > 0){
          fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ leverage: v }) })
            .then(function(){ loadConfig(); })
            .catch(function(){});
        }
      });
      orderLev._bound = true;
    }
    if (orderPos && !orderPos._bound){
      orderPos.addEventListener('change', function(e){
        var raw = e.target.value;
        var v = (raw===''? null : Number(raw));
        if (v===null || (!isNaN(v) && v>=0)){
          fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ override_position_size: v }) })
            .then(function(){ loadConfig(); })
            .catch(function(){});
        }
      });
      orderPos._bound = true;
    }
    if (orderPosEnable && !orderPosEnable._bound){
      orderPosEnable.addEventListener('change', function(e){
        var enabled = !!e.target.checked;
        fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ override_enabled: enabled }) })
          .then(function(){ loadConfig(); })
          .catch(function(){});
      });
      orderPosEnable._bound = true;
    }

    // 绑定交易模式切换（优先使用模块实现）
    var simBtn = document.getElementById('simModeBtn');
    var liveBtn = document.getElementById('liveModeBtn');
    if (simBtn && !simBtn._bound){ simBtn.addEventListener('click', function(){ if (window.App?.mode?.set) App.mode.set('simulation'); else setTradingMode2('simulation'); }); simBtn._bound = true; }
    if (liveBtn && !liveBtn._bound){ liveBtn.addEventListener('click', function(){ if (window.App?.mode?.set) App.mode.set('live'); else setTradingMode2('live'); }); liveBtn._bound = true; }

    // 绑定刷新频率输入变更（移入统一初始化块，避免分散的事件绑定）
    var freqInput = document.getElementById('autoFreqInput');
    if (freqInput && !freqInput._bound){
      freqInput.addEventListener('change', function(e){
        var v = Number(e.target.value||'');
        if (!isNaN(v) && v > 0){
          fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ ai_frequency: v }) })
            .then(function(){ return loadConfig(); })
            .catch(function(){});
        }
      });
      freqInput._bound = true;
    }

    // 初始化主题切换器
    initThemeSwitcher();

    if (window.App && typeof App.bootstrap === 'function') { App.bootstrap(); } else { initPage(); }
  });
})();

// 加载与显示核心配置（杠杆、固定仓位）
async function loadConfig(){
  try{
    var r = await fetch('/api/config');
    var j = await r.json();
    if (!j || !j.success) return;
    var cfg = j.config || {};
    var levEl = document.getElementById('orderLeverage');
    var posEl = document.getElementById('orderPosSize');
    var enEl = document.getElementById('orderPosEnable');
    var freqInput = document.getElementById('autoFreqInput');
    var autoLabel = document.getElementById('autoFreqLabel');
    if (levEl){ levEl.value = (cfg.leverage!=null? String(cfg.leverage): ''); }
    if (posEl){ posEl.value = (cfg.override_position_size!=null? String(cfg.override_position_size): ''); }
    if (enEl){ enEl.checked = !!cfg.override_enabled; }
    if (freqInput){ freqInput.value = (cfg.ai_frequency!=null? String(cfg.ai_frequency): ''); }
    if (autoLabel){ autoLabel.textContent = (cfg.ai_frequency!=null? String(cfg.ai_frequency): '--'); }
    // 更新页面频率并重启自动刷新（使用全局 window.startAuto 以避免作用域问题）
    if (cfg.ai_frequency!=null){
      document.body.setAttribute('data-ai-freq', String(cfg.ai_frequency));
      try { if (window.startAuto) window.startAuto(); } catch(_){}
    }
  }catch(e){ /* 忽略 */ }
}

// 绑定刷新频率输入变更（在 DOMContentLoaded 内部附加）
// 已合并到主初始化块，避免重复的 DOMContentLoaded 监听