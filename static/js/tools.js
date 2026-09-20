/* NISAデータ室 シミュレーター。scripts/calc.py と同じ計算式。入力値は送信されません。 */
(function () {
  "use strict";
  var LIFETIME = 18000000, GROWTH_SUB = 12000000, TSUMI = 1200000, GROWTH = 2400000, TOTAL = TSUMI + GROWTH;

  function num(form, name, def) {
    var v = parseFloat(form.elements[name].value);
    return isFinite(v) ? v : def;
  }
  function yen(v) { return Math.round(v).toLocaleString("ja-JP") + "円"; }
  function man(v) { return Math.round(v / 10000).toLocaleString("ja-JP") + "万円"; }
  function fv(monthly, rate, years, initial) {
    var n = Math.round(years * 12), r = rate / 12;
    if (r === 0) return initial + monthly * n;
    var g = Math.pow(1 + r, n);
    return initial * g + monthly * ((g - 1) / r);
  }
  function fillPlan(yearly, done) {
    var y = Math.min(yearly, TOTAL), t = Math.min(y, TSUMI), g = Math.max(0, y - t);
    var remain = Math.max(0, LIFETIME - done), years;
    if (remain === 0) years = 0;
    else if (y <= 0) years = Infinity;
    else if (g === 0) years = remain / t;
    else {
      var yg = GROWTH_SUB / g;
      years = (yg * y >= remain) ? remain / y : yg + (remain - yg * y) / t;
    }
    return { annual: y, tsumitate: t, growth: g, years: years, capped: yearly > TOTAL };
  }
  function row(k, v, cls) { return '<div class="kv' + (cls ? " " + cls : "") + '"><dt>' + k + "</dt><dd>" + v + "</dd></div>"; }
  function warn(msg) { return '<p class="warn">' + msg + "</p>"; }

  var tools = {
    "nisa-simulator": function (f) {
      var m = Math.max(0, num(f, "monthly", 0)), ini = Math.max(0, num(f, "initial", 0));
      var rate = num(f, "rate", 0) / 100, years = Math.max(1, Math.min(60, num(f, "years", 1))), fee = num(f, "fee", 0) / 100;
      var net = rate - fee, val = fv(m, net, years, ini), prin = ini + m * Math.round(years * 12), gain = val - prin;
      var h = "<dl>" + row("将来の評価額（概算）", "<strong>" + man(val) + "</strong>", "big") +
        row("投資した元本の合計", man(prin)) + row("運用益（概算）", man(gain)) +
        row("実質の想定年利（年利−コスト）", (net * 100).toFixed(2) + "%") +
        row("年間の投資額", man(m * 12)) + "</dl>";
      if (m * 12 > TOTAL) h += warn("年間の投資額が新NISAの年間上限（360万円）を超えています。超えた分はNISA口座では買えません。");
      if (prin > LIFETIME) h += warn("元本の合計が生涯投資枠（1,800万円）を超えます。枠は購入時の取得価額（簿価）で管理され、超える分は課税口座での投資になります（売却による枠の再利用は考慮していません）。");
      var rows = "", step = years > 30 ? 5 : (years > 15 ? 2 : 1);
      for (var y = step; y <= years; y += step) {
        rows += "<tr><th scope='row'>" + y + "年後</th><td>" + man(ini + m * y * 12) + "</td><td>" + man(fv(m, net, y, ini)) + "</td></tr>";
      }
      h += '<div class="table-wrap"><table><caption>年ごとの推移（概算）</caption><thead><tr><th scope="col">経過</th><th scope="col">元本</th><th scope="col">評価額</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
      return h;
    },
    "fee-impact": function (f) {
      var m = Math.max(0, num(f, "monthly", 0)), years = Math.max(1, Math.min(60, num(f, "years", 1)));
      var rate = num(f, "rate", 0) / 100, a = num(f, "feeA", 0) / 100, b = num(f, "feeB", 0) / 100;
      var va = fv(m, rate - a, years, 0), vb = fv(m, rate - b, years, 0), prin = m * Math.round(years * 12);
      var diff = va - vb, more = diff >= 0 ? "A" : "B";
      var h = "<dl>" + row("商品A（コスト " + (a * 100).toFixed(2) + "%）", man(va)) +
        row("商品B（コスト " + (b * 100).toFixed(2) + "%）", man(vb)) +
        row("差額（" + more + "の方が多い）", "<strong>" + man(Math.abs(diff)) + "</strong>", "big") +
        row("元本の合計（共通）", man(prin)) + "</dl>";
      h += '<p class="hint">コストの差は毎年の運用成果から差し引かれるため、期間が長いほど差が広がります。ただし、実際の運用成績は商品ごとに異なり、コストが低い方が常に有利とは限りません。</p>';
      return h;
    },
    "frame-planner": function (f) {
      var m = Math.max(0, num(f, "monthly", 0)), bonus = Math.max(0, num(f, "bonus", 0)), done = Math.max(0, num(f, "done", 0));
      var yearly = m * 12 + bonus * 2, p = fillPlan(yearly, done);
      var yrs = p.years === Infinity ? "―" : (p.years === 0 ? "枠は使い切り済み" : p.years.toFixed(1) + "年");
      var h = "<dl>" + row("年間の投資額（想定）", man(yearly)) +
        row("うち つみたて投資枠", man(p.tsumitate) + "（上限120万円）") +
        row("うち 成長投資枠", man(p.growth) + "（上限240万円）") +
        row("生涯投資枠1,800万円に届くまで", "<strong>" + yrs + "</strong>", "big") +
        row("残りの枠（簿価）", man(Math.max(0, LIFETIME - done))) + "</dl>";
      if (p.capped) h += warn("年間の投資額が上限（360万円）を超えています。計算は上限の360万円で行っています。");
      if (p.growth > 0 && GROWTH_SUB / p.growth * (p.tsumitate + p.growth) < LIFETIME - done)
        h += '<p class="hint">成長投資枠の生涯上限（1,200万円）に先に届くため、その後はつみたて投資枠（年120万円）のみで枠を埋めていく計算になっています。</p>';
      return h;
    }
  };

  if (typeof document !== "undefined") document.querySelectorAll("form.calc").forEach(function (form) {
    var key = form.getAttribute("data-tool"), out = document.querySelector('[data-result="' + key + '"]');
    function run() { out.innerHTML = tools[key](form); }
    form.addEventListener("input", run);
    form.addEventListener("submit", function (e) { e.preventDefault(); run(); });
    run();
  });
  if (typeof module !== "undefined") module.exports = { fv: fv, fillPlan: fillPlan };
})();
