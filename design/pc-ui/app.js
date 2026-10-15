// whoisspy PC 游戏界面稿件 · 共享交互（纯展示用，按页面元素存在性自适应）
// ===== 星空 =====
document.querySelectorAll('.stars').forEach(function (box) {
  var html = '';
  for (var i = 0; i < 34; i++) {
    var size = 1.5 + ((i * 13) % 5) * 0.55;
    html += '<span class="star' + (i % 9 === 0 ? ' bright' : '') + '" style="left:' + ((i * 61.8) % 100) +
      '%;top:' + ((i * 37.7) % 55) + '%;width:' + size + 'px;height:' + size + 'px;animation-delay:' + ((i % 7) * 0.4) + 's"></span>';
  }
  box.innerHTML = html;
});

// ===== 画板入场 =====
var frames = document.querySelectorAll('.frame');
if ('IntersectionObserver' in window) {
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('in'); }
    });
  }, { threshold: .12 });
  frames.forEach(function (f) { io.observe(f); });
} else {
  frames.forEach(function (f) { f.classList.add('in'); });
}

// ===== 游戏模式菜单 =====
var modeBtn = document.getElementById('modeBtn');
if (modeBtn) {
  modeBtn.addEventListener('click', function () {
    var menu = document.getElementById('modeMenu');
    menu.hidden = !menu.hidden;
    var caret = modeBtn.querySelector('.caret');
    if (caret) { caret.classList.toggle('up', !menu.hidden); }
  });
}

// ===== 节奏控制（暂停 / 倍速 / 逐帧） =====
document.querySelectorAll('.pace-play').forEach(function (play) {
  play.addEventListener('click', function () {
    var paused = play.textContent.indexOf('暂停') >= 0;
    play.textContent = paused ? '▶ 继续' : '⏸ 暂停';
  });
});
document.querySelectorAll('.speeds').forEach(function (speeds) {
  speeds.addEventListener('click', function (e) {
    var b = e.target.closest('.speed');
    if (!b) return;
    speeds.querySelectorAll('.speed').forEach(function (s) { s.classList.remove('on'); });
    b.classList.add('on');
  });
});

// ===== 创建对局：座位类型 / 预设 / 摘要 =====
var seatSegs = document.querySelectorAll('.seat-row .seg');
function refreshSummary() {
  var human = document.querySelectorAll('.seat-row .seg button.on[data-type="human"]').length;
  var total = seatSegs.length;
  var count = document.getElementById('seatCount');
  var summary = document.getElementById('createSummary');
  if (count) count.textContent = '已入座 ' + human + ' 人 · ' + (total - human) + ' 个 AI';
  if (summary) summary.innerHTML = '将开一局 <b>standard-9</b> · <b>' + human + '</b> 人入座 · <b>' + (total - human) +
    '</b> 个 AI 玩家 · 种子 42';
}
seatSegs.forEach(function (seg) {
  seg.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    seg.querySelectorAll('button').forEach(function (x) {
      x.classList.toggle('on', x === b);
      x.classList.toggle('ai', x === b && x.dataset.type === 'llm');
    });
    refreshSummary();
  });
});
document.querySelectorAll('.preset').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var preset = btn.dataset.preset;
    var pattern = preset === 'watch' ? [] : preset === 'duo' ? [2, 7] : [3];
    seatSegs.forEach(function (seg, i) {
      var human = pattern.indexOf(i + 1) >= 0;
      seg.querySelectorAll('button').forEach(function (x) {
        var active = human ? x.dataset.type === 'human' : x.dataset.type === 'llm';
        x.classList.toggle('on', active);
        x.classList.toggle('ai', active && x.dataset.type === 'llm');
      });
    });
    refreshSummary();
  });
});
if (seatSegs.length) refreshSummary();

// ===== 行动面板 tabs + 字数 =====
var tabs = document.getElementById('actionTabs');
if (tabs) {
  tabs.addEventListener('click', function (e) {
    var b = e.target.closest('.at');
    if (!b) return;
    tabs.querySelectorAll('.at').forEach(function (x) { x.classList.remove('on'); });
    b.classList.add('on');
    document.querySelectorAll('.action-body').forEach(function (pane) {
      pane.hidden = pane.dataset.pane !== b.dataset.tab;
    });
  });
}
var ta = document.querySelector('.action-body textarea');
if (ta) {
  var counter = document.querySelector('.action-body .counter');
  var update = function () {
    counter.textContent = ta.value.length + ' / 240';
    counter.classList.toggle('over', ta.value.length >= 240);
  };
  ta.addEventListener('input', update);
  update();
}

// ===== 投票 / 技能目标单选 =====
document.querySelectorAll('.target-grid').forEach(function (grid) {
  grid.addEventListener('click', function (e) {
    var t = e.target.closest('.target');
    if (!t || t.classList.contains('dead')) return;
    grid.querySelectorAll('.target').forEach(function (x) { x.classList.remove('on'); });
    t.classList.add('on');
  });
});
